// Sequential child inference keeps the fast model and ASR memory separate.
// No instrument command is executed by this application.
#include <cerrno>
#include <csignal>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include "intent_slots_native.h"
#include "vendor/json.hpp"
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static std::string run(const std::vector<std::string> &arguments) {
    int descriptors[2];
    if (pipe(descriptors)) throw std::runtime_error("Cannot create inference output pipe");
    pid_t child=fork();
    if (child<0) { close(descriptors[0]); close(descriptors[1]); throw std::runtime_error("Cannot start inference"); }
    if (!child) {
        close(descriptors[0]);
        if (dup2(descriptors[1],STDOUT_FILENO)<0) _exit(126);
        close(descriptors[1]);
        std::vector<char *> argv;
        for (const auto &value:arguments) argv.push_back(const_cast<char *>(value.c_str()));
        argv.push_back(nullptr); execv(argv[0],argv.data());
        std::cerr<<"Cannot execute "<<arguments[0]<<": "<<strerror(errno)<<'\n'; _exit(127);
    }
    close(descriptors[1]); std::string result; char buffer[4096]; bool too_large=false;
    for (;;) {
        ssize_t count=read(descriptors[0],buffer,sizeof(buffer));
        if (count<0 && errno==EINTR) continue;
        if (count<=0) break;
        if (result.size()+(size_t)count>1048576) { too_large=true; kill(child,SIGTERM); break; }
        result.append(buffer,(size_t)count);
    }
    close(descriptors[0]); int status=0;
    while (waitpid(child,&status,0)<0) if (errno!=EINTR) throw std::runtime_error("Cannot collect inference status");
    if (too_large || !WIFEXITED(status) || WEXITSTATUS(status)!=0) throw std::runtime_error("Inference failed; see stderr");
    size_t first=result.find_first_not_of(" \r\n\t"),last=result.find_last_not_of(" \r\n\t");
    if (first==std::string::npos || result[first]!='{' || result[last]!='}') throw std::runtime_error("Invalid native inference response");
    return result.substr(first,last-first+1);
}


using Json=nlohmann::json;
static Json response(const std::string &raw) {
    auto value=Json::parse(raw);
    if (!value.is_object() || !value.contains("intent_proposal") || !value["intent_proposal"].is_string())
        throw std::runtime_error("Invalid native inference fields");
    return value;
}
static Json parse_text(const std::string &text) {
    auto value=Json::parse("{"+smartbox_slots::json_fields(smartbox_slots::parse(text))+"}");
    value["parser_board_verified"]=false;
    value["board_runtime_verified"]=false;
    return value;
}
int main(int argc,char **argv) {
    try {
        if (argc==3 && std::string(argv[1])=="--parse-text") {
            auto result=parse_text(argv[2]); result["cascade_route"]="text_parser_diagnostic";
            std::cout<<result.dump()<<'\n'; return 0;
        }
        if (argc<3 || argc>4) throw std::runtime_error("Usage: smartbox_cascade package_directory audio.wav [auto|fast|asr]");
        std::string root=argv[1],audio=argv[2],mode=argc==4?argv[3]:"auto";
        if (mode!="auto" && mode!="fast" && mode!="asr") throw std::runtime_error("Mode must be auto, fast or asr");
        if (mode!="asr") {
            auto fast=response(run({root+"/bin/smartbox_voice_armv7",audio}));
            std::string intent=fast["intent_proposal"].get<std::string>();
            if (mode=="fast") { fast["cascade_route"]="fast_only"; std::cout<<fast.dump()<<'\n'; return 0; }
            if (intent.rfind("CMD_",0)==0 && intent!="CMD_SET_SIGNAL_FREQ") {
                fast["cascade_route"]="high_confidence_fast_command"; std::cout<<fast.dump()<<'\n'; return 0;
            }
        }
        auto asr=response(run({root+"/bin/smartbox_asr_armv7",audio,root+"/models/asr"}));
        if (!asr.contains("transcript") || !asr["transcript"].is_string()) throw std::runtime_error("Missing ASR transcript");
        // Reparse the transcript in the entry point; the paired acoustic models remain intact.
        // This also prevents outdated proposal fields from the ASR child surviving the patch.
        auto proposal=parse_text(asr["transcript"].get<std::string>());
        for (auto field=proposal.begin();field!=proposal.end();++field) asr[field.key()]=field.value();
        if (!proposal.contains("frequency_requires_instrument_range_validation")) asr.erase("frequency_requires_instrument_range_validation");
        asr["cascade_route"]=mode=="asr"?"asr_only":"asr_fallback";
        std::cout<<asr.dump()<<'\n';
    } catch (const std::exception &error) { std::cerr<<error.what()<<'\n'; return 2; }
    return 0;
}
