#!/usr/bin/env python3
"""Generate UTF8-aware C++ proposal rules from the selected Python rules.

ECMAScript regex does not treat UTF8 byte character classes as Unicode;
Chinese number classes are emitted as token alternatives instead.
"""
import argparse
import hashlib
import json
from pathlib import Path
import intent_slots as rules

TEMPLATE=r'''
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
__REGEX_CONSTANTS__
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
'''


def adapt(pattern):
    # Preserve groups and ASCII regex semantics; emit Chinese tokens as full
    # UTF8 alternatives rather than byte character classes.
    for chars in ['零〇一二两三四五六七八九十百千万亿','零〇一二两三四五六七八九']:
        pattern=pattern.replace('['+chars+']','(?:'+'|'.join(chars)+')')
    return pattern.replace(r'[+\-负]',r'(?:[+\-]|负)')


def generate(destination):
    patterns=dict(BLOCKED=rules.BLOCKED.pattern,IDENTIFY=rules.IDENTIFY.pattern,SET=rules.SET.pattern,
        NEXT=rules.NEXT.pattern,FREQUENCY=rules.FREQUENCY.pattern,
        MEASURE_FREQ=rules.MEASURE_FREQ.pattern,MEASURE_VPP=rules.MEASURE_VPP.pattern,
        MEASURE_RMS=rules.MEASURE_RMS.pattern,OUTPUT_ON=rules.OUTPUT_ON.pattern,
        OUTPUT_OFF=rules.OUTPUT_OFF.pattern,AMBIGUOUS_FREQUENCY=rules.AMBIGUOUS_FREQUENCY.pattern)
    declarations='\n'.join('static const std::regex '+name+'('+json.dumps(adapt(pattern),ensure_ascii=False)+');' for name,pattern in patterns.items())
    destination.write_text(TEMPLATE.replace('__REGEX_CONSTANTS__',declarations),encoding='utf-8')
    return dict(python_source_sha256=hashlib.sha256(Path(rules.__file__).read_bytes()).hexdigest(),
        native_header_sha256=hashlib.sha256(destination.read_bytes()).hexdigest())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    path=p.parse_args().output
    if path.exists():
        raise ValueError('Preserve generated native header')
    print(json.dumps(generate(path)),flush=True)
