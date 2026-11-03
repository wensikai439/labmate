// Linux ARMv7 offline WeNet CTC entry, using the bundled CPU ONNX Runtime.

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


extern "C" int smartbox_fbank(const char *path,float *output,int capacity) {
        try {int frames=0;auto values=fbank(read_wav(path),frames);
        if((int)values.size()>capacity)return -1;
        std::copy(values.begin(),values.end(),output);return frames;}catch(...){return -1;}}
    