#pragma once
#include "vendor/json.hpp"
#include <algorithm>
#include <cstdint>
#include <chrono>
#include <cerrno>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <string>
#include <stdexcept>
#include <thread>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/file.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <unistd.h>
namespace ipc {
using Json=nlohmann::json;
inline std::string canonical(const std::string&root){return std::filesystem::canonical(root).string();}
inline std::string socket_path(const std::string&root){uint32_t hash=2166136261u;for(unsigned char c:canonical(root)){hash^=c;hash*=16777619u;}return "/tmp/smartbox-v82-"+std::to_string(getuid())+"-"+std::to_string(hash)+".sock";}
inline int connect(const std::string&root){int fd=socket(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0);if(fd<0)return -1;sockaddr_un address{};address.sun_family=AF_UNIX;auto path=socket_path(root);std::memcpy(address.sun_path,path.c_str(),path.size()+1);if(::connect(fd,(sockaddr*)&address,sizeof(address))){close(fd);return -1;}return fd;}
inline void send(int fd,const Json&value){auto data=value.dump()+"\n";size_t at=0;while(at<data.size()){auto n=::send(fd,data.data()+at,data.size()-at,MSG_NOSIGNAL);if(n<0&&errno==EINTR)continue;if(n<=0)throw std::runtime_error("Service connection closed");at+=n;}}
inline Json read(int fd,size_t limit=1048576){std::string result;char bytes[4096];while(result.size()<limit){auto n=recv(fd,bytes,std::min(sizeof(bytes),limit-result.size()),0);if(n<0&&errno==EINTR)continue;if(n<=0)throw std::runtime_error("Service closed response");result.append(bytes,n);auto end=result.find('\n');if(end!=std::string::npos)return Json::parse(result.substr(0,end));}throw std::runtime_error("Service message too large");}
inline Json call(const std::string&root,const Json&request){int fd=connect(root);if(fd<0)throw std::runtime_error("Voice service is not running");try{send(fd,request);auto response=read(fd);close(fd);return response;}catch(...){close(fd);throw;}}
inline void launch(const std::string&root){std::filesystem::create_directories(root+"/run");pid_t child=fork();if(child<0)throw std::runtime_error("Cannot start voice service");if(child==0){setsid();pid_t daemon=fork();if(daemon<0)_exit(127);if(daemon>0)_exit(0);int log=open((root+"/run/service.log").c_str(),O_CREAT|O_APPEND|O_WRONLY,0600);int input=open("/dev/null",O_RDONLY);if(input>=0)dup2(input,0);if(log>=0){dup2(log,1);dup2(log,2);}std::string exe=root+"/bin/smartbox_voice_service";execl(exe.c_str(),exe.c_str(),root.c_str(),(char*)nullptr);_exit(127);}int status;while(waitpid(child,&status,0)<0&&errno==EINTR){}}
inline double ensure(const std::string&root){auto start=std::chrono::steady_clock::now();int fd=connect(root);if(fd>=0)close(fd);else launch(root);
    for(int attempt=0;attempt<1800;++attempt){try{auto state=call(root,{{"op","status"}});if(state.value("ready",false))return std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();if(state.contains("error"))throw std::runtime_error(state["error"].get<std::string>());}catch(const std::exception&e){if(attempt>10 && std::string(e.what()).find("load_failed")!=std::string::npos)throw;}
        std::this_thread::sleep_for(std::chrono::milliseconds(50));}
    throw std::runtime_error("Voice service startup timed out; inspect run/service.log");}
inline long meminfo(const std::string&key,const std::string&path="/proc/meminfo"){std::ifstream file(path);std::string line;while(std::getline(file,line))if(line.rfind(key+":",0)==0){try{return std::stol(line.substr(key.size()+1));}catch(...){return -1;}}return -1;}
}
