// One resident acoustic model per package. Microphone remains button-controlled.
#include "asr_core.h"
#include "service_ipc.h"
#include <atomic>
#include <condition_variable>
#include <csignal>
#include <mutex>
#include <sys/stat.h>
using Json=nlohmann::json;
static volatile sig_atomic_t stopped=0;
static int listener=-1;
static void stop_signal(int){stopped=1;if(listener>=0)close(listener);listener=-1;}
int main(int argc,char**argv){try{
    if(argc!=2)throw std::runtime_error("Usage: smartbox_voice_service package_dir");
    std::string root=ipc::canonical(argv[1]);std::filesystem::create_directories(root+"/run");
    int lock=open((root+"/run/service.lock").c_str(),O_CREAT|O_RDWR|O_CLOEXEC,0600);
    if(lock<0)throw std::runtime_error("Cannot create service lock");
    if(flock(lock,LOCK_EX|LOCK_NB)){close(lock);return 0;}
    std::ofstream(root+"/run/service.pid")<<getpid()<<std::endl;
    auto path=ipc::socket_path(root);unlink(path.c_str());
    listener=socket(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0);if(listener<0)throw std::runtime_error("Cannot create local socket");
    sockaddr_un address{};address.sun_family=AF_UNIX;std::memcpy(address.sun_path,path.c_str(),path.size()+1);
    if(bind(listener,(sockaddr*)&address,sizeof(address)) || chmod(path.c_str(),0600) || listen(listener,8))throw std::runtime_error("Cannot start local voice service");
    signal(SIGPIPE,SIG_IGN);signal(SIGTERM,stop_signal);signal(SIGINT,stop_signal);
    std::mutex mutex;std::condition_variable cv;bool ready=false,busy=false,quit=false;std::string failure;
    Json request;int request_fd=-1;unsigned long completed=0;double load_ms=0;
    std::thread worker([&]{
        try{
            ResidentAsr model(root+"/models/asr");
            {std::lock_guard<std::mutex>guard(mutex);load_ms=model.load_ms;ready=true;}
            for(;;){int fd;Json job;
                {std::unique_lock<std::mutex>guard(mutex);cv.wait(guard,[&]{return quit||request_fd>=0;});if(quit && request_fd<0)break;fd=request_fd;request_fd=-1;job=request;}
                try{Json result=Json::parse(model.recognize(job.at("audio")));result["asr_service_pid"]=getpid();result["model_load_count"]=1;result["service_model_load_ms"]=load_ms;result["service_model_reused"]=true;result["service_queue_wait_ms"]=0.;result["memory"]={{"process_rss_kib",ipc::meminfo("VmRSS","/proc/self/status")},{"process_swap_kib",ipc::meminfo("VmSwap","/proc/self/status")},{"system_available_kib",ipc::meminfo("MemAvailable")}};ipc::send(fd,result);}
                catch(const std::exception&e){try{ipc::send(fd,{{"error",e.what()}});}catch(...){}}
                close(fd);{std::lock_guard<std::mutex>guard(mutex);busy=false;++completed;}
            }
        }catch(const std::exception&e){std::lock_guard<std::mutex>guard(mutex);failure=std::string("load_failed: ")+e.what();}
    });
    while(!stopped){int fd=accept4(listener,nullptr,nullptr,SOCK_CLOEXEC);if(fd<0){if(stopped)break;if(errno==EINTR)continue;break;}
        try{
            timeval timeout{2,0};setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));auto command=ipc::read(fd,8192);std::string op=command.value("op","");
            std::lock_guard<std::mutex>guard(mutex);
            if(op=="status"){
                Json status={{"type","voice_service_status"},{"version","8.2"},{"ready",ready},{"busy",busy},{"asr_service_pid",getpid()},{"model_load_count",ready?1:0},{"model_load_ms",load_ms},{"completed_requests",completed},{"state",ready?(busy?"recognizing":"ready"):"loading"},{"microphone_opened_by_service",false},{"rss_kib",ipc::meminfo("VmRSS","/proc/self/status")},{"swap_kib",ipc::meminfo("VmSwap","/proc/self/status")}};
                if(!failure.empty())status["error"]=failure;ipc::send(fd,status);close(fd);
            }else if(op=="stop"){ipc::send(fd,{{"stopping",true}});close(fd);stopped=1;}
            else if(op=="recognize"){
                if(!failure.empty()){ipc::send(fd,{{"error",failure}});close(fd);}
                else if(!ready||busy){ipc::send(fd,{{"error",ready?"recognition_busy":"model_loading"},{"message",ready?"Previous recognition is still running; no extra request was queued":"Model is warming up"}});close(fd);}
                else{std::string audio=command.at("audio");if(audio.find_first_of("\n\r")!=std::string::npos || audio.size()>4096)throw std::runtime_error("Invalid WAV path");request=command;request_fd=fd;busy=true;cv.notify_one();}
            }else{ipc::send(fd,{{"error","unsupported_operation"}});close(fd);}
        }catch(const std::exception&e){try{ipc::send(fd,{{"error",e.what()}});}catch(...){}close(fd);}
    }
    {std::lock_guard<std::mutex>guard(mutex);quit=true;}cv.notify_one();worker.join();
    if(listener>=0)close(listener);unlink(path.c_str());close(lock);return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 2;}}
