// Compatible lightweight entry point: never constructs an acoustic session.
#include "service_ipc.h"
#include <iostream>
int main(int argc,char**argv){try{
    if(argc==3 && (std::string(argv[1])=="--warmup" || std::string(argv[1])=="--status" || std::string(argv[1])=="--stop")){
        std::string root=ipc::canonical(argv[2]);if(std::string(argv[1])=="--warmup"){double waited=ipc::ensure(root);auto value=ipc::call(root,{{"op","status"}});value["warmup_wait_ms"]=waited;std::cout<<value.dump()<<std::endl;}
        else std::cout<<ipc::call(root,{{"op",std::string(argv[1])=="--status"?"status":"stop"}}).dump()<<std::endl;return 0;
    }
    if(argc!=3)throw std::runtime_error("Usage: smartbox_asr_resident --server model_dir | audio.wav model_dir | --warmup/--status/--stop package_dir");
    std::string root=ipc::canonical(std::filesystem::absolute(argv[2]).lexically_normal().parent_path().parent_path().string());double waited=ipc::ensure(root);
    auto infer=[&](const std::string&file){auto value=ipc::call(root,{{"op","recognize"},{"audio",std::filesystem::absolute(file).string()}});value["service_startup_wait_ms"]=waited;waited=0;std::cout<<value.dump()<<std::endl;};
    if(std::string(argv[1])=="--server"){
        auto state=ipc::call(root,{{"op","status"}});std::cout<<ipc::Json({{"type","ready"},{"model_load_ms",waited},{"asr_service_pid",state["asr_service_pid"]},{"model_load_count",state["model_load_count"]},{"service_reused",true}}).dump()<<std::endl;
        std::string line;while(std::getline(std::cin,line))if(!line.empty())infer(line);
    }else infer(argv[1]);return 0;
}catch(const std::exception&e){std::cout<<ipc::Json({{"error",e.what()}}).dump()<<std::endl;return 2;}}
