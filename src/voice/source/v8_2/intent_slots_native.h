
#pragma once
#include <algorithm>
#include <cctype>
#include <cmath>
#include <iomanip>
#include <map>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
namespace smartbox_slots {
struct Result { std::string intent="UNMATCHED",reason="empty_transcript"; bool has_frequency=false; long double frequency=0.; };
inline std::vector<std::string> codepoints(const std::string &text) {
  std::vector<std::string> result;
  for (size_t i=0;i<text.size();) {
    unsigned char c=(unsigned char)text[i];
    size_t n=c<128?1:(c&0xe0)==0xc0?2:(c&0xf0)==0xe0?3:(c&0xf8)==0xf0?4:0;
    if (!n || i+n>text.size()) throw std::runtime_error("Invalid UTF8 text");
    result.push_back(text.substr(i,n)); i+=n;
  }
  return result;
}
inline std::string normalize(const std::string &text) {
  std::string result;
  const std::vector<std::string> punctuation={"，","。","！","？","、","；","：",",",":",";","!","?"};
  for (auto token:codepoints(text)) {
    if (std::find(punctuation.begin(),punctuation.end(),token)!=punctuation.end()) continue;
    if (token.size()==1) {
      unsigned char c=(unsigned char)token[0];
      if (std::isspace(c)) continue;
      token[0]=(char)std::tolower(c);
    }
    result+=token;
  }
  return result;
}
inline long double number_value(std::string token) {
  size_t p=token.find("负"); if (p==0) token.replace(0,std::string("负").size(),"-");
  static const std::regex arabic(R"([+\-]?[0-9]+(?:\.[0-9]+)?)");
  if (std::regex_match(token,arabic)) return std::stold(token);
  int sign=1;
  if (!token.empty() && (token[0]=='-' || token[0]=='+')) { if (token[0]=='-') sign=-1; token.erase(0,1); }
  const std::map<std::string,int> digits={{"零",0},{"〇",0},{"一",1},{"二",2},{"两",2},{"三",3},{"四",4},{"五",5},{"六",6},{"七",7},{"八",8},{"九",9}};
  const std::map<std::string,int> small={{"十",10},{"百",100},{"千",1000}};
  const std::map<std::string,int> large={{"万",10000},{"亿",100000000}};
  auto points=codepoints(token);
  auto separator=std::find(points.begin(),points.end(),"点");
  size_t integer=(size_t)(separator-points.begin());
  if (integer>=2 && (points[integer-2]=="百" || points[integer-2]=="千") &&
      digits.count(points[integer-1]) && digits.at(points[integer-1])>0)
    throw std::runtime_error("Ambiguous abbreviated Chinese number");
  long double total=0,section=0,current=0;
  for (size_t i=0;i<integer;++i) {
    const auto &c=points[i];
    if (digits.count(c)) current=current*10+digits.at(c);
    else if (small.count(c)) { section+=(current?current:1)*small.at(c); current=0; }
    else if (large.count(c)) {
      section+=current;
      if (c=="亿") total=(total+section)*large.at(c); else total+=section*large.at(c);
      section=current=0;
    } else throw std::runtime_error("Unsupported numeral");
  }
  long double value=total+section+current;
  if (separator!=points.end()) {
    if (integer+1==points.size()) throw std::runtime_error("Missing decimal fraction");
    long double place=.1L;
    for (size_t i=integer+1;i<points.size();++i) {
      if (!digits.count(points[i])) throw std::runtime_error("Invalid decimal fraction");
      value+=digits.at(points[i])*place; place/=10;
    }
  }
  return sign*value;
}
static const std::regex BLOCKED("不要|不能|禁止|无需|不必|勿|先别|请别|你别|别再|别急|别(?:打开|开启|关闭|测|读|设|调|识别|查询)|是否|要不要|为什么|是不是|如果|他说|她说|老师(?:说|讲|解释)|例如|示例|解释|什么意思|是什么意思|是什么原理|什么原理|有什么关系|定义|含义|刚才|这四个字|怎么写|怎么读|我想了解|我的问题|我想问|请回答.*问题|课本|讲义|课堂笔记|课堂上|课堂中|不(?:准|允许|需要|打开|开启|关闭|关掉|测|读|设|调|识别|查询|使能|禁用|启动|停止)|能不能|能否|可不可以|别(?:把|将|开通|启动|使能|禁用|停止|关掉|暂停|停掉|恢复|启用|计算|显示|获取|提示|继续|进入)|的意思|这句话|几个字|这个词|报告.*(?:记录|介绍|写|提)|同学.*提到|我听说|我正在复习|课堂笔记|我记得");
static const std::regex IDENTIFY("(?:识别|辨认|认出).*(?:仪器|设备|示波器|信号源|发生器|电源)|(?:读取|读出|查看|显示|查询|获取|确认|检查).*(?:型号|仪器名称|设备名称)|(?:读取|读出|查看|显示|查询|获取|确认|检查).*(?:仪器|设备|示波器|信号源|发生器|电源).*(?:型号|名称)|(?:列出|显示|查询|查看).*(?:可控仪器|连接的仪器|连接的设备)|确认.*(?:连接|设备)|检查.*仪器|看看.*(?:设备|仪器).*是什么|(?:读取|查看|显示).*(?:仪器|型号)");
static const std::regex SET("(?:设置|设(?:为|成|到|定)|设(?=频率|信号|输出|发生器)|调(?:为|到|至|成|整|节)|改(?:为|成|到)|更改|修改).*(?:[+\\-]|负)?(?:\\d+(?:\\.\\d+)?|(?:零|〇|一|二|两|三|四|五|六|七|八|九|十|百|千|万|亿)+(?:点(?:零|〇|一|二|两|三|四|五|六|七|八|九)+)?)(?:兆赫|千赫|赫兹|mhz|khz|hz)|(?:设置|设(?:为|成|到|定)|设(?=频率|信号|输出|发生器)|调(?:为|到|至|成|整|节)|改(?:为|成|到)|更改|修改).*频率|频率.*(?:设置|设(?:为|成|到|定)|设(?=频率|信号|输出|发生器)|调(?:为|到|至|成|整|节)|改(?:为|成|到)|更改|修改)");
static const std::regex NEXT("下一步|继续实验|继续下一|下一个.*(?:实验步骤|任务)|下一项.*实验任务|(?:后面|随后|接下来|接着|后续).*(?:实验步骤|实验操作|操作|步骤|该.*做)|继续显示.*实验操作|后面的实验步骤");
static const std::regex FREQUENCY("((?:[+\\-]|负)?(?:\\d+(?:\\.\\d+)?|(?:零|〇|一|二|两|三|四|五|六|七|八|九|十|百|千|万|亿)+?(?:点(?:零|〇|一|二|两|三|四|五|六|七|八|九)+)?))(兆赫兹|兆赫|mhz|千赫兹|千赫|khz|赫兹|hz)");
static const std::regex MEASURE_FREQ("(?:测量(?!记录|任务|步骤|方法|方案|指令|结果)|测一下|测出|测(?=频率|峰|有效|均方根|当前|这个|信号|示波器|仪器|通道)|量(?=频率|峰|有效|当前|这个|信号)|读取|读出|读一下|读(?=频率|峰|有效|均方根|当前|这个|信号|示波器|仪器|通道)|获取|查询|查看|显示|计算|检测).*(?:频率)|(?:把|将).*(?:频率).*(?:测量(?!记录|任务|步骤|方法|方案|指令|结果)|测一下|测出|测(?=频率|峰|有效|均方根|当前|这个|信号|示波器|仪器|通道)|量(?=频率|峰|有效|当前|这个|信号)|读取|读出|读一下|读(?=频率|峰|有效|均方根|当前|这个|信号|示波器|仪器|通道)|获取|查询|查看|显示|计算|检测)");
static const std::regex MEASURE_VPP("(?:测量(?!记录|任务|步骤|方法|方案|指令|结果)|测一下|测出|测(?=频率|峰|有效|均方根|当前|这个|信号|示波器|仪器|通道)|量(?=频率|峰|有效|当前|这个|信号)|读取|读出|读一下|读(?=频率|峰|有效|均方根|当前|这个|信号|示波器|仪器|通道)|获取|查询|查看|显示|计算|检测).*(?:峰峰|峰到峰|vpp)|(?:把|将).*(?:峰峰|峰到峰|vpp).*(?:测量(?!记录|任务|步骤|方法|方案|指令|结果)|测一下|测出|测(?=频率|峰|有效|均方根|当前|这个|信号|示波器|仪器|通道)|量(?=频率|峰|有效|当前|这个|信号)|读取|读出|读一下|读(?=频率|峰|有效|均方根|当前|这个|信号|示波器|仪器|通道)|获取|查询|查看|显示|计算|检测)");
static const std::regex MEASURE_RMS("(?:测量(?!记录|任务|步骤|方法|方案|指令|结果)|测一下|测出|测(?=频率|峰|有效|均方根|当前|这个|信号|示波器|仪器|通道)|量(?=频率|峰|有效|当前|这个|信号)|读取|读出|读一下|读(?=频率|峰|有效|均方根|当前|这个|信号|示波器|仪器|通道)|获取|查询|查看|显示|计算|检测).*(?:有效值|有效电压|均方根|rms)|(?:把|将).*(?:有效值|有效电压|均方根|rms).*(?:测量(?!记录|任务|步骤|方法|方案|指令|结果)|测一下|测出|测(?=频率|峰|有效|均方根|当前|这个|信号|示波器|仪器|通道)|量(?=频率|峰|有效|当前|这个|信号)|读取|读出|读一下|读(?=频率|峰|有效|均方根|当前|这个|信号|示波器|仪器|通道)|获取|查询|查看|显示|计算|检测)");
static const std::regex OUTPUT_ON("(?:打开|开启|使能|启用|恢复|启动|开通).*(?:输出|信号源|信号发生器)|(?:把|将).*(?:输出|信号源|信号发生器).*(?:打开|开启|使能|启用|恢复|启动|开通)");
static const std::regex OUTPUT_OFF("(?:关闭|停止|禁用|关掉|暂停|停掉).*(?:输出|信号源|信号发生器)|(?:把|将).*(?:输出|信号源|信号发生器).*(?:关闭|停止|禁用|关掉|暂停|停掉)");
static const std::regex AMBIGUOUS_FREQUENCY("(?:[+\\-]|负)?(?:\\d+(?:\\.\\d+)?|(?:零|〇|一|二|两|三|四|五|六|七|八|九|十|百|千|万|亿)+(?:点(?:零|〇|一|二|两|三|四|五|六|七|八|九)+)?)\\s*(?:到|至|或|或者|~|～|/|—|和|与|、|,|，)\\s*(?:[+\\-]|负)?(?:\\d+(?:\\.\\d+)?|(?:零|〇|一|二|两|三|四|五|六|七|八|九|十|百|千|万|亿)+(?:点(?:零|〇|一|二|两|三|四|五|六|七|八|九)+)?)|\\d+\\.(?:\\d*\\.)+\\d+");
inline Result parse(const std::string &transcript) {
  Result result; const auto text=normalize(transcript);
  if (text.empty()) return result;
  if (std::regex_search(text,BLOCKED)) { result.reason="negative_question_or_reported_command_requires_review"; return result; }
  std::vector<std::string> candidates;
  if (std::regex_search(text,IDENTIFY)) candidates.push_back("CMD_IDENTIFY_INSTRUMENT");
  if (std::regex_search(text,SET)) candidates.push_back("CMD_SET_SIGNAL_FREQ");
  if (std::regex_search(text,MEASURE_FREQ)) candidates.push_back("CMD_MEASURE_FREQ");
  if (std::regex_search(text,MEASURE_VPP)) candidates.push_back("CMD_MEASURE_VPP");
  if (std::regex_search(text,MEASURE_RMS)) candidates.push_back("CMD_MEASURE_RMS");
  if (std::regex_search(text,OUTPUT_ON)) candidates.push_back("CMD_OUTPUT_ON");
  if (std::regex_search(text,OUTPUT_OFF)) candidates.push_back("CMD_OUTPUT_OFF");
  if (std::regex_search(text,NEXT)) candidates.push_back("CMD_NEXT");
  if (candidates.size()!=1) { result.reason="multiple_or_unsupported_intents"; return result; }
  if (candidates[0]=="CMD_SET_SIGNAL_FREQ") {
    if (std::regex_search(transcript,AMBIGUOUS_FREQUENCY)) { result.reason="ambiguous_or_invalid_frequency"; return result; }
    std::vector<std::smatch> matches;
    for (std::sregex_iterator i(text.begin(),text.end(),FREQUENCY),end;i!=end;++i) matches.push_back(*i);
    if (matches.size()!=1) { result.reason="missing_or_multiple_explicit_frequency_values"; return result; }
    auto preceding=codepoints(text.substr(0,(size_t)matches[0].position()));
    const std::vector<std::string> number_tokens={"0","1","2","3","4","5","6","7","8","9",".","点","零","〇","一","二","两","三","四","五","六","七","八","九","十","百","千","万","亿"};
    if (!preceding.empty() && std::find(number_tokens.begin(),number_tokens.end(),preceding.back())!=number_tokens.end()) { result.reason="ambiguous_or_invalid_frequency"; return result; }
    try {
      long double value=number_value(matches[0][1].str());
      auto unit=matches[0][2].str();
      if (unit.rfind("m",0)==0 || unit.rfind("兆",0)==0) value*=1000000;
      else if (unit.rfind("k",0)==0 || unit.rfind("千",0)==0) value*=1000;
      if (!(value>0) || !std::isfinite(value)) throw std::runtime_error("Invalid frequency");
      result.has_frequency=true; result.frequency=value;
    } catch (...) { result.reason="ambiguous_or_invalid_frequency"; return result; }
  }
  result.intent=candidates[0]; result.reason="single_supported_command_proposal"; return result;
}
inline std::string json_fields(const Result &r) {
  std::ostringstream output;
  output<<"\"intent_proposal\":\""<<r.intent<<"\",\"frequency_hz\":";
  if (r.has_frequency) output<<std::setprecision(17)<<(double)r.frequency; else output<<"null";
  output<<",\"confirmation_required\":true,\"instrument_control_executed\":false,"
           "\"parser\":\"constrained_zh_rules_v6r2_native\",\"reason\":\""<<r.reason<<"\"";
  if (r.has_frequency) output<<",\"frequency_requires_instrument_range_validation\":true";
  return output.str();
}
} // namespace smartbox_slots
