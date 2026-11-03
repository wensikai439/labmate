// Linux ARMv7 offline WeNet CTC entry, using the bundled CPU ONNX Runtime.
#include <onnxruntime_cxx_api.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include "asr_frontend_constants.h"
#include "ctc_context_decoder.h"
#include "intent_slots_native.h"

static unsigned le16(const unsigned char *p) { return p[0] | ((unsigned)p[1] << 8); }
static uint32_t le32(const unsigned char *p) { return p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }

static std::vector<float> read_wav(const char *path) {
    std::unique_ptr<FILE, decltype(&fclose)> file(fopen(path, "rb"), fclose);
    if (!file) throw std::runtime_error("Cannot open WAV");
    unsigned char buffer[16];
    if (fread(buffer, 1, 12, file.get()) != 12 || memcmp(buffer, "RIFF", 4) || memcmp(buffer + 8, "WAVE", 4))
        throw std::runtime_error("Expected RIFF WAVE");
    bool format = false;
    while (fread(buffer, 1, 8, file.get()) == 8) {
        uint32_t length = le32(buffer + 4);
        if (!memcmp(buffer, "fmt ", 4)) {
            if (length < 16 || fread(buffer, 1, 16, file.get()) != 16) throw std::runtime_error("Invalid WAV format");
            format = le16(buffer) == 1 && le16(buffer + 2) == 1 && le32(buffer + 4) == 16000 && le16(buffer + 14) == 16;
            if (length > 0x7fffffffU || fseek(file.get(), (long)(length - 16 + (length & 1)), SEEK_CUR))
                throw std::runtime_error("Invalid format chunk size");
        } else if (!memcmp(buffer, "data", 4)) {
            if (!format || length < 800 || length > 384000 || (length & 1))
                throw std::runtime_error("Use 16 kHz mono PCM16 WAV, 25 ms to 12 seconds");
            std::vector<float> wave(length / 2);
            for (float &sample : wave) {
                if (fread(buffer, 1, 2, file.get()) != 2) throw std::runtime_error("Truncated WAV");
                sample = (float)(int16_t)le16(buffer);
            }
            return wave;
        } else if (length > 0x7fffffffU || fseek(file.get(), (long)(length + (length & 1)), SEEK_CUR)) {
            throw std::runtime_error("Invalid WAV chunk size");
        }
    }
    throw std::runtime_error("WAV data missing");
}

static void fft(double *real, double *imag) {
    for (int i = 1, j = 0; i < 512; ++i) {
        int bit = 256;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) { std::swap(real[i], real[j]); std::swap(imag[i], imag[j]); }
    }
    for (int width = 2; width <= 512; width *= 2) {
        double angle = -6.2831853071795864769 / width;
        double cr = cos(angle), ci = sin(angle);
        for (int start = 0; start < 512; start += width) {
            double wr = 1, wi = 0;
            for (int j = 0; j < width / 2; ++j) {
                int a = start + j, b = a + width / 2;
                double br = real[b] * wr - imag[b] * wi, bi = real[b] * wi + imag[b] * wr;
                real[b] = real[a] - br; imag[b] = imag[a] - bi;
                real[a] += br; imag[a] += bi;
                double next = wr * cr - wi * ci;
                wi = wr * ci + wi * cr; wr = next;
            }
        }
    }
}

static std::vector<float> fbank(const std::vector<float> &wave, int &frames) {
    frames = 1 + ((int)wave.size() - 400) / 160;
    std::vector<float> features((size_t)frames * 80);
    for (int t = 0; t < frames; ++t) {
        double real[512] = {}, imag[512] = {}; float values[400], mean = 0;
        for (int i = 0; i < 400; ++i) mean += wave[t * 160 + i];
        mean /= 400;
        for (int i = 0; i < 400; ++i) values[i] = wave[t * 160 + i] - mean;
        for (int i = 0; i < 400; ++i) real[i] = (values[i] - .97f * values[i ? i - 1 : 0]) * ASR_WINDOW[i];
        fft(real, imag);
        float power[257];
        for (int k = 0; k < 257; ++k) power[k] = real[k] * real[k] + imag[k] * imag[k];
        for (int bin = 0; bin < 80; ++bin) {
            float energy = 0;
            static const auto ranges = [] {
                std::array<std::array<int,2>,80> result{};
                for (int b=0;b<80;++b) {
                    int first=0,last=257;
                    while(first<last && ASR_MEL[first][b]==0.f) ++first;
                    while(last>first && ASR_MEL[last-1][b]==0.f) --last;
                    result[b]={first,last};
                }
                return result;
            }();
            for (int k=ranges[bin][0];k<ranges[bin][1];++k) energy += power[k] * ASR_MEL[k][bin];
            features[t * 80 + bin] = logf(std::max(energy, 1.1920928955078125e-7f));
        }
    }
    return features;
}

static std::string escaped(const std::string &text) {
    std::string result;
    for (unsigned char c : text) {
        if (c == '\\' || c == '"') { result += '\\'; result += (char)c; }
        else if (c < 32) {
            char code[7]; snprintf(code, sizeof(code), "\\u%04x", c); result += code;
        } else result += (char)c;
    }
    return result;
}


#include <cstdlib>
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
        
        int threads=getenv("ASR_THREADS")?std::stoi(getenv("ASR_THREADS")):2;
        options.SetIntraOpNumThreads(threads); options.SetInterOpNumThreads(1);

        
        options.DisableMemPattern();
        if(!getenv("ASR_ARENA") || std::string(getenv("ASR_ARENA"))!="1")options.DisableCpuMemArena();

        
        std::string level=getenv("ASR_OPT")?getenv("ASR_OPT"):"basic";
        options.SetGraphOptimizationLevel(level=="all"?GraphOptimizationLevel::ORT_ENABLE_ALL:level=="extended"?GraphOptimizationLevel::ORT_ENABLE_EXTENDED:GraphOptimizationLevel::ORT_ENABLE_BASIC);
        if(getenv("ASR_PROFILE"))options.EnableProfiling(getenv("ASR_PROFILE"));

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
        double combined_decode_ms=millis(decode_start);
        auto proposal=smartbox_slots::parse(text);
        struct rusage usage{};getrusage(RUSAGE_SELF,&usage);
        std::ostringstream out;
        out<<"{\"transcript\":\""<<escaped(text)<<"\",\"decoder\":\""
           <<(config.beam?"offline_ctc_context_prefix":"offline_ctc_greedy")
           <<"\",\"backend\":\"PS_CPU_ONNX_INT8_resident\","
           <<smartbox_slots::json_fields(proposal)
           <<",\"board_runtime_verified\":false,\"timing_ms\":{\"frontend\":"<<frontend_ms
           <<",\"encoder\":"<<encoder_ms<<",\"ctc_decode\":"<<combined_decode_ms
           <<",\"total\":"<<millis(begin)<<"},\"process_peak_rss_kib\":"<<usage.ru_maxrss<<"}";
        return out.str();
    }
};
