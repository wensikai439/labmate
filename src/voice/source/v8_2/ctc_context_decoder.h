// CPU CTC prefix beam for the exported WeNet vocabulary. Acoustic prefix
// probabilities are separate from context scores; unfinished matches roll
// back at final ranking. Project implementation inspired by WeNet context.
#pragma once
#include <algorithm>
#include <cmath>
#include <fstream>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace smartbox_ctc {
using Prefix=std::vector<int>;
struct Config { int beam=0,topk=10; double context=0.; };
struct Scores { double blank=-std::numeric_limits<double>::infinity();
                double nonblank=-std::numeric_limits<double>::infinity(); };
inline double logadd(double a,double b) {
  if (a==-std::numeric_limits<double>::infinity()) return b;
  if (b==-std::numeric_limits<double>::infinity()) return a;
  double hi=std::max(a,b),lo=std::min(a,b);
  return hi+std::log1p(std::exp(lo-hi));
}
inline double total(const Scores &s) { return logadd(s.blank,s.nonblank); }
inline std::vector<Prefix> hotwords(const std::map<int,std::string> &symbols) {
  std::map<std::string,int> lookup;
  for (const auto &item:symbols) lookup[item.second]=item.first;
  std::vector<Prefix> result;
  for (const std::string word:{"RMS","VPP","有效值","峰峰值","均方根","峰到峰"}) {
    Prefix tokens;
    for (size_t i=0;i<word.size();) {
      unsigned char c=(unsigned char)word[i];
      size_t bytes=c<0x80?1:(c&0xe0)==0xc0?2:(c&0xf0)==0xe0?3:(c&0xf8)==0xf0?4:0;
      if (!bytes || i+bytes>word.size()) throw std::runtime_error("Invalid UTF8 hotword");
      auto token=lookup.find(word.substr(i,bytes));
      if (token==lookup.end()) throw std::runtime_error("Hotword outside model vocabulary");
      tokens.push_back(token->second); i+=bytes;
    }
    result.push_back(tokens);
  }
  return result;
}
inline double potential(const Prefix &prefix,const std::vector<Prefix> &words,bool final=false) {
  int completed=0; double partial=0.;
  for (const auto &word:words) {
    for (size_t i=0;i+word.size()<=prefix.size();++i)
      if (std::equal(word.begin(),word.end(),prefix.begin()+i)) ++completed;
    if (!final) for (size_t n=1;n<word.size() && n<=prefix.size();++n)
      if (std::equal(word.begin(),word.begin()+n,prefix.end()-n))
        partial=std::max(partial,(double)n/word.size());
  }
  return completed+partial;
}
inline Config load_config(const std::string &path) {
  Config config;
  std::ifstream file(path);
  if (!file) return config; // Compatible with the preserved V4 deployment.
  std::string key; double value;
  while (file>>key>>value) {
    if (key=="beam_size") config.beam=(int)value;
    else if (key=="topk") config.topk=(int)value;
    else if (key=="context_weight") config.context=value;
    else throw std::runtime_error("Unknown decoder configuration field");
  }
  if (!file.eof() || config.beam<0 || config.beam>16 || config.topk<1 || config.topk>32 ||
      !std::isfinite(config.context) || config.context<0 || config.context>2)
    throw std::runtime_error("Invalid bounded decoder configuration");
  return config;
}
inline std::string decode(const float *values,int frames,int vocab,
                         const std::map<int,std::string> &symbols,const Config &config) {
  if (frames<1 || vocab!=(int)symbols.size()) throw std::runtime_error("Invalid CTC shape");
  std::string text;
  if (!config.beam) {
    int previous=-1;
    for (int t=0;t<frames;++t) {
      const float *row=values+(size_t)t*vocab;
      int best=(int)(std::max_element(row,row+vocab)-row);
      if (best!=0 && best!=previous && !symbols.at(best).empty() && symbols.at(best)[0]!='<') text+=symbols.at(best);
      previous=best;
    }
    return text;
  }
  const auto words=hotwords(symbols);
  std::vector<int> allowed;
  for (const auto &item:symbols)
    if (item.first && !item.second.empty() && item.second[0]!='<') allowed.push_back(item.first);
  std::vector<std::pair<Prefix,Scores>> beams{{Prefix{},Scores{0.,-std::numeric_limits<double>::infinity()}}};
  for (int t=0;t<frames;++t) {
    const float *row=values+(size_t)t*vocab;
    std::vector<int> choices=allowed;
    size_t count=std::min((size_t)config.topk,choices.size());
    std::partial_sort(choices.begin(),choices.begin()+count,choices.end(),[&](int a,int b) {
      return row[a]!=row[b]?row[a]>row[b]:a<b;
    });
    choices.resize(count);
    std::map<Prefix,Scores> next;
    for (const auto &item:beams) {
      const Prefix &prefix=item.first;
      const Scores &s=item.second;
      Scores &same=next[prefix];
      same.blank=logadd(same.blank,total(s)+(double)row[0]);
      for (int c:choices) {
        Prefix extended=prefix; extended.push_back(c);
        if (!prefix.empty() && c==prefix.back()) {
          same.nonblank=logadd(same.nonblank,s.nonblank+(double)row[c]);
          auto &n=next[extended]; n.nonblank=logadd(n.nonblank,s.blank+(double)row[c]);
        } else {
          auto &n=next[extended]; n.nonblank=logadd(n.nonblank,total(s)+(double)row[c]);
        }
      }
    }
    beams.assign(next.begin(),next.end());
    std::stable_sort(beams.begin(),beams.end(),[&](const auto &a,const auto &b) {
      return total(a.second)+config.context*potential(a.first,words)>
             total(b.second)+config.context*potential(b.first,words);
    });
    if (beams.size()>(size_t)config.beam) beams.resize(config.beam);
  }
  auto best=std::max_element(beams.begin(),beams.end(),[&](const auto &a,const auto &b) {
    return total(a.second)+config.context*potential(a.first,words,true)<
           total(b.second)+config.context*potential(b.first,words,true);
  });
  for (int token:best->first) text+=symbols.at(token);
  return text;
}
} // namespace smartbox_ctc
