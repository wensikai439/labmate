// Continuous capture and conservative WebRTC endpointing with resident V8 ASR.
#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <spawn.h>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include "vendor/json.hpp"
#include "intent_slots_native.h"
#include "vad_training_phrases.h"
extern "C" {
#include "webrtc/common_audio/vad/include/webrtc_vad.h"
}
extern char **environ;
using Json=nlohmann::json;
using Clock=std::chrono::steady_clock;
static volatile sig_atomic_t stopping=0;
static volatile sig_atomic_t recording_pid=-1;
static void on_signal(int){stopping=1;if(recording_pid>0)kill(recording_pid,SIGTERM);}
static double elapsed(Clock::time_point t){return std::chrono::duration<double,std::milli>(Clock::now()-t).count();}
static std::mutex output_mutex;
static void emit(const Json &value){std::lock_guard<std::mutex> lock(output_mutex);std::cout<<value.dump()<<std::endl;}
static int setting(const char *key,int fallback,int low,int high){
    const char *raw=getenv(key);if(!raw)return fallback;
    char *last=nullptr;long value=strtol(raw,&last,10);
    if(!*raw || *last || value<low || value>high)throw std::runtime_error(std::string("Invalid ")+key);
    return (int)value;
}
static pid_t spawn(const std::vector<std::string> &args,int input,int output){
    std::vector<char*> argv;for(const auto &arg:args)argv.push_back(const_cast<char*>(arg.c_str()));argv.push_back(nullptr);
    posix_spawn_file_actions_t actions;posix_spawn_file_actions_init(&actions);
    if(input>=0)posix_spawn_file_actions_adddup2(&actions,input,STDIN_FILENO);
    if(output>=0)posix_spawn_file_actions_adddup2(&actions,output,STDOUT_FILENO);
    pid_t pid=-1;int rc=posix_spawnp(&pid,argv[0],&actions,nullptr,argv.data(),environ);
    posix_spawn_file_actions_destroy(&actions);
    if(rc)throw std::runtime_error(std::string("Cannot launch ")+args[0]+": "+strerror(rc));
    return pid;
}
static void collect(pid_t pid){int status=0;while(waitpid(pid,&status,0)<0){if(errno!=EINTR)throw std::runtime_error("waitpid failed");}if(!WIFEXITED(status)||WEXITSTATUS(status))throw std::runtime_error("Child program failed");}
static std::string line_from(FILE *file){char *buffer=nullptr;size_t capacity=0;ssize_t n=getline(&buffer,&capacity,file);if(n<0){free(buffer);throw std::runtime_error("Worker closed output");}std::string value(buffer,(size_t)n);free(buffer);if(value.size()>1048576)throw std::runtime_error("Worker reply too large");return value;}
static Json run_fast(const std::string &root,const std::string &wave){
    int pipes[2];if(pipe2(pipes,O_CLOEXEC))throw std::runtime_error("pipe failed");
    pid_t pid;
    try{pid=spawn({root+"/bin/smartbox_voice_armv7",wave},-1,pipes[1]);}catch(...){close(pipes[0]);close(pipes[1]);throw;}
    close(pipes[1]);FILE *file=fdopen(pipes[0],"r");std::string response;
    try{response=line_from(file);}catch(...){fclose(file);collect(pid);throw;}
    fclose(file);collect(pid);return Json::parse(response);
}
class AsrWorker {
    pid_t pid=-1;FILE *reader=nullptr,*writer=nullptr;
public:
    explicit AsrWorker(const std::string &root){
        int input[2],output[2];if(pipe2(input,O_CLOEXEC))throw std::runtime_error("pipe failed");
        if(pipe2(output,O_CLOEXEC)){close(input[0]);close(input[1]);throw std::runtime_error("pipe failed");}
        try{pid=spawn({root+"/bin/smartbox_asr_resident","--server",root+"/models/asr"},input[0],output[1]);}
        catch(...){for(int fd:input)close(fd);for(int fd:output)close(fd);throw;}
        close(input[0]);close(output[1]);reader=fdopen(output[0],"r");writer=fdopen(input[1],"w");
        try{auto ready=Json::parse(line_from(reader));if(ready.value("type","")!="ready")throw std::runtime_error("ASR initialization failed");std::cerr<<"ASR ready; one-time model load "<<ready.value("model_load_ms",0.0)<<" ms\n";}
        catch(...){fclose(writer);writer=nullptr;fclose(reader);reader=nullptr;waitpid(pid,nullptr,0);pid=-1;throw;}
    }
    ~AsrWorker(){if(writer)fclose(writer);if(reader)fclose(reader);if(pid>0)waitpid(pid,nullptr,0);}
    Json recognize(const std::string &path){
        if(path.find_first_of("\n\r")!=std::string::npos)throw std::runtime_error("Invalid WAV path");
        if(fprintf(writer,"%s\n",path.c_str())<0 || fflush(writer))throw std::runtime_error("Cannot request ASR");
        auto value=Json::parse(line_from(reader));if(value.contains("error"))throw std::runtime_error(value["error"].get<std::string>());return value;
    }
};
static Json recognize(const std::string &root,const std::string &path,const std::string &mode,AsrWorker *asr){
    auto begin=Clock::now();Json result;
    if(mode!="asr"){
        result=run_fast(root,path);std::string intent=result.at("intent_proposal").get<std::string>();
        if(mode=="fast" || (intent.rfind("CMD_",0)==0 && intent!="CMD_SET_SIGNAL_FREQ")){
            result["cascade_route"]=mode=="fast"?"fast_only":"high_confidence_fast_command";
            result["pipeline_ms"]=elapsed(begin);return result;
        }
    }
    if(!asr)throw std::runtime_error("ASR worker unavailable");result=asr->recognize(path);
    result["parser_board_verified"]=false;
    result["cascade_route"]=mode=="asr"?"asr_only":"asr_fallback";
    result["pipeline_ms"]=elapsed(begin);return result;
}
static Json apply_vad_rules(Json value){
    auto proposal=smartbox_slots::parse(value.at("transcript").get<std::string>());
    bool supplemented=false;
    if(proposal.intent=="UNMATCHED" && proposal.reason=="multiple_or_unsupported_intents"){
        const auto normalized=smartbox_slots::normalize(value["transcript"].get<std::string>());
        // These are complete imperative command grammars, not substring
        // guesses. The original negation/question rejection runs first.
        static const std::string polite="^(?:(?:请你|请|帮我|现在|麻烦你|麻烦|先|给我))*";
        static const std::regex identity(polite+"(?:查|查询|查看|确认|识别|读取|获取)(?:一下)?(?:这台|当前|连接的)?(?:仪器|设备)(?:的)?(?:身份信息|身份|型号|类型)$");
        static const std::regex frequency(polite+"(?:采集|读取|获取|读出)(?:一下|一次)?(?:当前)?(?:信号的)?频率(?:读数|数值|结果|值)?$");
        static const std::regex output_on(polite+"(?:(?:让|使)?(?:信号源|信号发生器))?(?:开始|启动|开启|打开)(?:输出|信号输出)(?:测试波形)?$");
        if(std::regex_match(normalized,identity)){proposal.intent="CMD_IDENTIFY_INSTRUMENT";supplemented=true;}
        else if(std::regex_match(normalized,frequency)){proposal.intent="CMD_MEASURE_FREQ";supplemented=true;}
        else if(std::regex_match(normalized,output_on)){proposal.intent="CMD_OUTPUT_ON";supplemented=true;}
        if(supplemented)proposal.reason="supported_complete_command_alias";
        static const auto phrases=[] {
            std::map<std::string,std::string> result;
            for(const auto &item:SMARTBOX_TRAINING_PHRASES){auto key=smartbox_slots::normalize(item.first);auto found=result.find(key);if(found==result.end())result[key]=item.second;else if(found->second!=item.second)found->second="";}
            return result;
        }();
        auto found=phrases.find(smartbox_slots::normalize(value["transcript"].get<std::string>()));
        if(!supplemented && found!=phrases.end() && !found->second.empty()){
            proposal.intent=found->second;proposal.reason="supported_exact_training_phrase";supplemented=true;
        }
    }
    auto fields=Json::parse("{"+smartbox_slots::json_fields(proposal)+"}");
    for(auto item=fields.begin();item!=fields.end();++item)value[item.key()]=item.value();
    value["parser_board_verified"]=false;
    if(supplemented)value["parser"]="constrained_zh_rules_v6r2_plus_exact_training_phrases";
    return value;
}
static void put16(FILE *f,uint16_t v){fputc(v&255,f);fputc(v>>8,f);}
static void put32(FILE *f,uint32_t v){put16(f,v&65535);put16(f,v>>16);}
static void save_wav(const std::string &path,const std::vector<int16_t> &samples){
    FILE *f=fopen(path.c_str(),"wb");if(!f)throw std::runtime_error("Cannot write WAV");
    fwrite("RIFF",1,4,f);put32(f,36+samples.size()*2);fwrite("WAVEfmt ",1,8,f);put32(f,16);put16(f,1);put16(f,1);put32(f,16000);put32(f,32000);put16(f,2);put16(f,16);fwrite("data",1,4,f);put32(f,samples.size()*2);
    for(int16_t sample:samples)put16(f,(uint16_t)sample);
    if(ferror(f)){fclose(f);throw std::runtime_error("WAV write failed");}fclose(f);
}
static std::vector<int16_t> load_wav(const std::string &path){
    std::ifstream file(path,std::ios::binary);std::vector<unsigned char> data((std::istreambuf_iterator<char>(file)),{});
    auto u16=[&](size_t p){if(p+2>data.size())throw std::runtime_error("Truncated WAV");return (unsigned)data[p]|((unsigned)data[p+1]<<8);};
    auto u32=[&](size_t p){return (uint32_t)u16(p)|((uint32_t)u16(p+2)<<16);};
    if(data.size()<44 || memcmp(data.data(),"RIFF",4) || memcmp(data.data()+8,"WAVE",4))throw std::runtime_error("Expected WAV");
    bool valid=false;for(size_t p=12;p+8<=data.size();){uint32_t size=u32(p+4);if(p+8+size>data.size())throw std::runtime_error("Truncated chunk");if(!memcmp(data.data()+p,"fmt ",4)){valid=size>=16 && u16(p+8)==1 && u16(p+10)==1 && u32(p+12)==16000 && u16(p+22)==16;}else if(!memcmp(data.data()+p,"data",4)){if(!valid || (size&1))throw std::runtime_error("Use mono PCM16 16kHz WAV");std::vector<int16_t> result(size/2);for(size_t i=0;i<result.size();++i)result[i]=(int16_t)u16(p+8+i*2);return result;}p+=8+size+(size&1);}throw std::runtime_error("No audio data");
}
struct Segment {std::vector<int16_t> audio;int tail_ms=0;Clock::time_point queued;};
class Endpoint {
    VadInst *vad=nullptr;std::deque<int16_t> prefix;std::vector<int16_t> active;
    int voiced=0,silent=0;bool discard=false;
    int tail_frames=setting("VAD_SILENCE_MS",800,400,2000)/20;
    int prefix_samples=setting("VAD_PREROLL_MS",320,100,1000)*16;
public:
    Endpoint(){vad=WebRtcVad_Create();if(!vad || WebRtcVad_Init(vad) || WebRtcVad_set_mode(vad,0))throw std::runtime_error("Cannot initialize WebRTC VAD");}
    ~Endpoint(){if(vad)WebRtcVad_Free(vad);}
    bool feed(const int16_t *frame,Segment &ready){
        int speech=WebRtcVad_Process(vad,16000,frame,320);if(speech<0)throw std::runtime_error("VAD failure");
        if(discard){silent=speech?0:silent+1;if(silent>=tail_frames){discard=false;silent=0;prefix.clear();}return false;}
        if(active.empty()){
            if(!speech){prefix.insert(prefix.end(),frame,frame+320);while((int)prefix.size()>prefix_samples)prefix.pop_front();return false;}
            active.assign(prefix.begin(),prefix.end());prefix.clear();voiced=0;silent=0;
        }
        active.insert(active.end(),frame,frame+320);if(speech){++voiced;silent=0;}else ++silent;
        if(active.size()>192000){active.clear();voiced=0;discard=true;silent=0;emit({{"error","utterance_too_long"},{"message","Speech exceeds 12 seconds; please repeat a shorter instruction"}});return false;}
        if(silent>=tail_frames){
            bool enough=voiced>=8;ready.audio.swap(active);active.clear();ready.tail_ms=silent*20;ready.queued=Clock::now();
            prefix.clear();voiced=0;silent=0;return enough;
        }return false;
    }
};
static int segment_file(const std::string &input,const std::string &directory){
    if(mkdir(directory.c_str(),0700) && errno!=EEXIST)throw std::runtime_error("Cannot create segment directory");
    auto audio=load_wav(input);audio.resize(audio.size()+32000,0);Endpoint endpoint;int count=0;Segment segment;
    for(size_t start=0;start+320<=audio.size();start+=320)if(endpoint.feed(audio.data()+start,segment)){
        std::string path=directory+"/segment_"+std::to_string(count++)+".wav";save_wav(path,segment.audio);emit({{"segment",path},{"samples",segment.audio.size()},{"endpoint_tail_ms",segment.tail_ms}});
    }return 0;
}
int main(int argc,char **argv){
    signal(SIGPIPE,SIG_IGN);signal(SIGINT,on_signal);signal(SIGTERM,on_signal);
    try{
        if(argc==4 && std::string(argv[1])=="--segment")return segment_file(argv[2],argv[3]);
        if(argc==3 && std::string(argv[1])=="--parse-vad"){emit(apply_vad_rules({{"transcript",argv[2]}}));return 0;}
        if(argc<2)throw std::runtime_error("Usage: smartbox_voice_live package_dir [--once] [--fast|--asr] [--fixed4] [audio.wav]");
        std::string root=argv[1],mode="auto",input;bool once=false,fixed=false;
        for(int i=2;i<argc;++i){std::string arg=argv[i];if(arg=="--once")once=true;else if(arg=="--fast")mode="fast";else if(arg=="--asr")mode="asr";else if(arg=="--fixed4")fixed=true;else if(arg=="--vad")fixed=false;else if(arg.rfind("--",0)==0 || !input.empty())throw std::runtime_error("Unknown option or multiple input files");else input=arg;}
        std::unique_ptr<AsrWorker> asr;if(mode!="fast")asr=std::make_unique<AsrWorker>(root);
        if(!input.empty()){emit(recognize(root,input,mode,asr.get()));return 0;}
        int pipes[2];if(pipe2(pipes,O_CLOEXEC))throw std::runtime_error("pipe failed");
        const char *device=getenv("ALSA_DEVICE");pid_t recorder=spawn({"arecord","-q","-t","raw","-D",device?device:"default","-f","S16_LE","-r","16000","-c","1"},-1,pipes[1]);close(pipes[1]);
        recording_pid=recorder;
        std::deque<Segment> queue;std::mutex mutex;std::condition_variable changed;bool done=false;std::atomic<bool> capture_failed{false};
        std::thread capture([&]{
            try{
                Endpoint endpoint;Segment fixed_audio;int seconds=setting("RECORD_SECONDS",4,1,12);std::array<int16_t,320> frame{};bool one_captured=false;
                while(!stopping){size_t have=0;while(have<sizeof(frame) && !stopping){ssize_t n=read(pipes[0],(char*)frame.data()+have,sizeof(frame)-have);if(n<0 && errno==EINTR)continue;if(n<=0)break;have+=(size_t)n;}if(have!=sizeof(frame))break;
                    Segment segment;bool ready=false;
                    if(fixed){fixed_audio.audio.insert(fixed_audio.audio.end(),frame.begin(),frame.end());if(fixed_audio.audio.size()>=(size_t)seconds*16000){segment.audio.swap(fixed_audio.audio);segment.queued=Clock::now();ready=true;}}
                    else ready=endpoint.feed(frame.data(),segment);
                    if(ready){std::unique_lock<std::mutex> lock(mutex);if(queue.size()>=2){emit({{"error","recognition_backlog"},{"message","Recognition is slower than speech; this utterance was not processed"}});}else{queue.push_back(std::move(segment));changed.notify_one();}if(once){one_captured=true;break;}}
                }
                if(!stopping && !one_captured){capture_failed=true;emit({{"error","microphone_stream_closed"},{"message","Recording ended unexpectedly; check the ALSA device"}});}
            }catch(const std::exception &e){capture_failed=true;emit({{"error",e.what()}});}
            close(pipes[0]);kill(recorder,SIGTERM);waitpid(recorder,nullptr,0);recording_pid=-1;{std::lock_guard<std::mutex> lock(mutex);done=true;}changed.notify_all();
        });
        std::cerr<<"Ready. Speak an instruction; Ctrl+C stops.\n";
        int exit_code=0;
        while(true){Segment segment;{std::unique_lock<std::mutex> lock(mutex);changed.wait(lock,[&]{return done||!queue.empty();});if(queue.empty())break;segment=std::move(queue.front());queue.pop_front();}
            const char *tmp=getenv("TMPDIR");std::string pattern=std::string(tmp?tmp:"/tmp")+"/smartbox-v81-XXXXXX";std::vector<char> name(pattern.begin(),pattern.end());name.push_back(0);int fd=mkstemp(name.data());if(fd<0){emit({{"error","Cannot create temporary audio file"}});exit_code=2;continue;}close(fd);std::string path=name.data();
            try{save_wav(path,segment.audio);
                // V6 fast-model thresholds were not calibrated for VAD crops.
                // Full V8 ASR validates endpointed audio; fixed-window/file
                // modes retain the original cascade and all its thresholds.
                const bool guarded=!fixed && mode=="auto";
                auto result=recognize(root,path,guarded?"asr":mode,asr.get());
                if(guarded){result=apply_vad_rules(result);result["cascade_route"]="vad_asr_guarded";}
                result["endpoint_tail_ms"]=segment.tail_ms;result["capture_duration_ms"]=segment.audio.size()/16.0;result["endpoint_to_result_ms"]=elapsed(segment.queued);emit(result);}
            catch(const std::exception &e){emit({{"error",e.what()}});exit_code=2;}unlink(path.c_str());
        }
        capture.join();return capture_failed?2:exit_code;
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 2;}
}
