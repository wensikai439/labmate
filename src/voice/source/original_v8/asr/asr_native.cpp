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
            for (int k = 0; k < 257; ++k) energy += power[k] * ASR_MEL[k][bin];
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

int main(int argc, char **argv) {
    if (argc != 3) { std::cerr << "Usage: smartbox_asr_armv7 audio.wav model_directory\n"; return 2; }
    try {
        int frames = 0;
        auto features = fbank(read_wav(argv[1]), frames);
        if (frames < 7) throw std::runtime_error("Utterance too short for the convolutional encoder");
        std::string directory = argv[2];
        Ort::Env env(ORT_LOGGING_LEVEL_WARNING, "smartbox_asr");
        Ort::SessionOptions options;
        options.SetIntraOpNumThreads(2); options.SetInterOpNumThreads(1);
        options.DisableMemPattern(); options.DisableCpuMemArena();
        options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_BASIC);
        auto memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
        Ort::AllocatorWithDefaultOptions allocator;
        std::vector<float> cnn((size_t)ASR_BLOCKS * ASR_OUTPUT_SIZE * (ASR_CNN_KERNEL - 1), 0), attention(1, 0);
        int64_t offset = 0, required = -1;
        bool mask = true;
        std::array<int64_t, 3> chunk_shape = {1, frames, 80}, mask_shape = {0, 0, 0};
        std::array<int64_t, 4> attention_shape = {ASR_BLOCKS, ASR_HEADS, 0, ASR_OUTPUT_SIZE / ASR_HEADS * 2};
        std::array<int64_t, 4> cnn_shape = {ASR_BLOCKS, 1, ASR_OUTPUT_SIZE, ASR_CNN_KERNEL - 1};
        Ort::Value encoded{nullptr};
        {
            Ort::Session encoder(env, (directory + "/encoder.quant.onnx").c_str(), options);
            std::vector<std::string> names;
            std::vector<Ort::Value> inputs;
            for (size_t i = 0; i < encoder.GetInputCount(); ++i) {
                names.emplace_back(encoder.GetInputNameAllocated(i, allocator).get());
                const auto &name = names.back();
                if (name == "chunk") inputs.emplace_back(Ort::Value::CreateTensor<float>(memory, features.data(), features.size(), chunk_shape.data(), 3));
                else if (name == "offset") inputs.emplace_back(Ort::Value::CreateTensor<int64_t>(memory, &offset, 1, nullptr, 0));
                else if (name == "required_cache_size") inputs.emplace_back(Ort::Value::CreateTensor<int64_t>(memory, &required, 1, nullptr, 0));
                else if (name == "att_cache") inputs.emplace_back(Ort::Value::CreateTensor<float>(memory, attention.data(), 0, attention_shape.data(), 4));
                else if (name == "cnn_cache") inputs.emplace_back(Ort::Value::CreateTensor<float>(memory, cnn.data(), cnn.size(), cnn_shape.data(), 4));
                else if (name == "att_mask") inputs.emplace_back(Ort::Value::CreateTensor<bool>(memory, &mask, 0, mask_shape.data(), 3));
                else throw std::runtime_error("Unexpected encoder input: " + name);
            }
            std::vector<const char *> input_names;
            for (const auto &name : names) input_names.push_back(name.c_str());
            std::string output = encoder.GetOutputNameAllocated(0, allocator).get();
            const char *outputs[] = {output.c_str()};
            auto values = encoder.Run(Ort::RunOptions{nullptr}, input_names.data(), inputs.data(), inputs.size(), outputs, 1);
            encoded = std::move(values[0]);
        }
        Ort::Session ctc(env, (directory + "/ctc.quant.onnx").c_str(), options);
        std::string input = ctc.GetInputNameAllocated(0, allocator).get(), output = ctc.GetOutputNameAllocated(0, allocator).get();
        const char *input_names[] = {input.c_str()}, *output_names[] = {output.c_str()};
        auto values = ctc.Run(Ort::RunOptions{nullptr}, input_names, &encoded, 1, output_names, 1);
        auto shape = values[0].GetTensorTypeAndShapeInfo().GetShape();
        if (shape.size() != 3 || shape[0] != 1 || shape[2] != ASR_VOCAB_SIZE) throw std::runtime_error("Unexpected CTC output shape");
        std::map<int, std::string> symbols;
        std::ifstream dictionary(directory + "/units.txt");
        std::string symbol; int id;
        while (dictionary >> symbol >> id) symbols[id] = symbol;
        if ((int)symbols.size() != ASR_VOCAB_SIZE) throw std::runtime_error("Vocabulary differs from exported model");
        const float *logits = values[0].GetTensorData<float>();
        const auto config=smartbox_ctc::load_config(directory+"/decoder.conf");
        const auto text=smartbox_ctc::decode(logits,(int)shape[1],ASR_VOCAB_SIZE,symbols,config);
        const auto proposal=smartbox_slots::parse(text);
        std::cout << "{\"transcript\":\"" << escaped(text)
                  << "\",\"decoder\":\"" << (config.beam?"offline_ctc_context_prefix":"offline_ctc_greedy")
                  << "\",\"backend\":\"PS_CPU_ONNX_INT8_native\","
                  << smartbox_slots::json_fields(proposal)
                  << ",\"board_runtime_verified\":false}\n";
    } catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 2; }
    return 0;
}
