#!/usr/bin/env python3
"""Reuse the V8 acoustic frontend and decoding code without numerical edits."""
from pathlib import Path
import sys

root = Path(sys.argv[1])
reference = root / 'reference/SmartBox_ZedBoard_Voice_V8_20261020'
original = (reference / 'source/asr/asr_native.cpp').read_text()
prefix = original.split('int main(int argc, char **argv) {')[0]
# Zero mel coefficients do not contribute to the accumulator. Retain the exact
# order of every nonzero operation, the float64 FFT and the original log floor.
old_mel = 'for (int k = 0; k < 257; ++k) energy += power[k] * ASR_MEL[k][bin];'
new_mel = '''static const auto ranges = [] {
                std::array<std::array<int,2>,80> result{};
                for (int b=0;b<80;++b) {
                    int first=0,last=257;
                    while(first<last && ASR_MEL[first][b]==0.f) ++first;
                    while(last>first && ASR_MEL[last-1][b]==0.f) --last;
                    result[b]={first,last};
                }
                return result;
            }();
            for (int k=ranges[bin][0];k<ranges[bin][1];++k) energy += power[k] * ASR_MEL[k][bin];'''
assert prefix.count(old_mel)==1
prefix=prefix.replace(old_mel,new_mel)
body = r'''
#include <chrono>
#include <sstream>
#include <sys/resource.h>
using Clock = std::chrono::steady_clock;
static double millis(Clock::time_point start) {
    return std::chrono::duration<double,std::milli>(Clock::now()-start).count();
}
class ResidentAsr {
    Ort::Env env{ORT_LOGGING_LEVEL_WARNING,"smartbox_resident"};
    Ort::SessionOptions options;
    std::unique_ptr<Ort::Session> encoder,ctc;
    std::map<int,std::string> symbols;
    smartbox_ctc::Config config;
public:
    double load_ms=0;
    explicit ResidentAsr(const std::string &directory) {
        auto begin=Clock::now();
        options.SetIntraOpNumThreads(2); options.SetInterOpNumThreads(1);
        options.DisableMemPattern(); options.DisableCpuMemArena();
        options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_BASIC);
        options.AddConfigEntry("session.intra_op.allow_spinning","0");
        options.AddConfigEntry("session.inter_op.allow_spinning","0");
        encoder=std::make_unique<Ort::Session>(env,(directory+"/encoder.quant.onnx").c_str(),options);
        ctc=std::make_unique<Ort::Session>(env,(directory+"/ctc.quant.onnx").c_str(),options);
        if (encoder->GetInputCount()!=1 || ctc->GetInputCount()!=1)
            throw std::runtime_error("This resident runtime requires the V8 single-input offline graph");
        Ort::AllocatorWithDefaultOptions allocator;
        if (std::string(encoder->GetInputNameAllocated(0,allocator).get())!="chunk")
            throw std::runtime_error("Unexpected V8 encoder input");
        std::ifstream dictionary(directory+"/units.txt");
        std::string symbol; int id;
        while(dictionary>>symbol>>id) symbols[id]=symbol;
        if(symbols.size()!=ASR_VOCAB_SIZE) throw std::runtime_error("Vocabulary mismatch");
        config=smartbox_ctc::load_config(directory+"/decoder.conf");
        load_ms=millis(begin);
    }
    std::string recognize(const std::string &path) {
        auto begin=Clock::now(); int frames=0;
        auto features=fbank(read_wav(path.c_str()),frames);
        if(frames<7) throw std::runtime_error("Utterance too short for encoder");
        double frontend_ms=millis(begin);
        auto memory=Ort::MemoryInfo::CreateCpu(OrtArenaAllocator,OrtMemTypeDefault);
        std::array<int64_t,3> dims={1,frames,80};
        auto tensor=Ort::Value::CreateTensor<float>(memory,features.data(),features.size(),dims.data(),3);
        const char *input_names[]={"chunk"};
        Ort::AllocatorWithDefaultOptions allocator;
        std::string encoder_output=encoder->GetOutputNameAllocated(0,allocator).get();
        const char *encoder_outputs[]={encoder_output.c_str()};
        auto encode_start=Clock::now();
        auto encoded=encoder->Run(Ort::RunOptions{nullptr},input_names,&tensor,1,encoder_outputs,1);
        double encoder_ms=millis(encode_start);
        std::string ctc_input=ctc->GetInputNameAllocated(0,allocator).get();
        std::string ctc_output=ctc->GetOutputNameAllocated(0,allocator).get();
        const char *ctc_inputs[]={ctc_input.c_str()},*ctc_outputs[]={ctc_output.c_str()};
        auto decode_start=Clock::now();
        auto values=ctc->Run(Ort::RunOptions{nullptr},ctc_inputs,encoded.data(),1,ctc_outputs,1);
        auto shape=values[0].GetTensorTypeAndShapeInfo().GetShape();
        if(shape.size()!=3 || shape[0]!=1 || shape[2]!=ASR_VOCAB_SIZE)
            throw std::runtime_error("Unexpected CTC output shape");
        auto text=smartbox_ctc::decode(values[0].GetTensorData<float>(),(int)shape[1],ASR_VOCAB_SIZE,symbols,config);
        auto proposal=smartbox_slots::parse(text);
        struct rusage usage{};getrusage(RUSAGE_SELF,&usage);
        std::ostringstream out;
        out<<"{\"transcript\":\""<<escaped(text)<<"\",\"decoder\":\""
           <<(config.beam?"offline_ctc_context_prefix":"offline_ctc_greedy")
           <<"\",\"backend\":\"PS_CPU_ONNX_INT8_resident\","
           <<smartbox_slots::json_fields(proposal)
           <<",\"board_runtime_verified\":false,\"timing_ms\":{\"frontend\":"<<frontend_ms
           <<",\"encoder\":"<<encoder_ms<<",\"ctc_decode\":"<<millis(decode_start)
           <<",\"total\":"<<millis(begin)<<"},\"process_peak_rss_kib\":"<<usage.ru_maxrss<<"}";
        return out.str();
    }
};
int main(int argc,char **argv) {
    try {
        if(argc!=3) throw std::runtime_error("Usage: smartbox_asr_resident --server model_dir OR audio.wav model_dir");
        ResidentAsr model(argv[2]);
        if(std::string(argv[1])!="--server") {
            std::cout<<model.recognize(argv[1])<<std::endl; return 0;
        }
        std::cout<<"{\"type\":\"ready\",\"model_load_ms\":"<<model.load_ms<<"}"<<std::endl;
        std::string line;
        while(std::getline(std::cin,line)) {
            if(line.empty()) continue;
            try {std::cout<<model.recognize(line)<<std::endl;}
            catch(const std::exception &e) {std::cout<<"{\"error\":\""<<escaped(e.what())<<"\"}"<<std::endl;}
        }
    } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 2;}
}
'''
out=root/'src/asr_resident.cpp'
out.write_text(prefix+body)
for name,text in [('baseline',original.split('int main(int argc, char **argv) {')[0]),('resident',prefix)]:
    for header in ['#include <onnxruntime_cxx_api.h>','#include "ctc_context_decoder.h"','#include "intent_slots_native.h"']:
        text=text.replace(header,'')
    text+='''\nextern "C" int smartbox_fbank(const char *path,float *output,int capacity) {
        try {int frames=0;auto values=fbank(read_wav(path),frames);
        if((int)values.size()>capacity)return -1;
        std::copy(values.begin(),values.end(),output);return frames;}catch(...){return -1;}}
    '''
    (root/'src'/('frontend_'+name+'.cpp')).write_text(text)
for header in ('asr_frontend_constants.h','ctc_context_decoder.h','intent_slots_native.h'):
    (root/'src'/header).write_bytes((reference/'source/asr'/header).read_bytes())
