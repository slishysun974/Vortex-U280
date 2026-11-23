#include <algorithm>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
#include <sched.h>

using Words = std::vector<std::uint32_t>;
extern "C" void iris_cpu(const std::uint32_t*, const std::uint32_t*, std::uint32_t*, std::size_t);

Words read_words(const std::string& path) {
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    const std::streamoff bytes = f.tellg();
    if (bytes <= 0 || bytes % 4 != 0) throw std::runtime_error("invalid array " + path);
    Words words(static_cast<std::size_t>(bytes) / 4);
    f.seekg(0);
    if (!f.read(reinterpret_cast<char*>(words.data()), bytes)) throw std::runtime_error("short input " + path);
    return words;
}

struct Batch {
    Words x, sums, initial, expected, out;
};

int main(int argc, char** argv) {
    if (argc != 3) return 2;
    const std::string root = argv[1];
    std::ifstream schedule(argv[2]);
    std::map<std::string,Batch> batches;
    int seq, trial;
    unsigned n;
    std::string key, scope;
    while (schedule >> seq >> key >> n >> scope >> trial) {
        if (!batches.count(key)) {
            const auto inputs = root + "/inputs/" + key + "/";
            auto& b = batches[key];
            b.x = read_words(inputs + "x.input.bin");
            b.sums = read_words(inputs + "sums.input.bin");
            b.initial = read_words(inputs + "out.input.bin");
            b.expected = read_words(root + "/" + key + ".expected.bin");
            if (b.x.size() < 8 + 4*n || b.sums.size() != 20 || b.initial.size() != b.x.size()
                    || b.expected.size() != b.x.size()) throw std::runtime_error("invalid shape");
            b.out.resize(b.initial.size());
        }
        auto& b = batches.at(key);
        std::copy(b.initial.begin(), b.initial.end(), b.out.begin());
        const auto start = std::chrono::steady_clock::now();
        iris_cpu(b.x.data()+4, b.sums.data()+4, b.out.data()+4, n);
        const auto end = std::chrono::steady_clock::now();
        if (b.out != b.expected) throw std::runtime_error("full allocation mismatch: " + key);
        const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end-start).count();
        std::cout << seq << ',' << key << ',' << scope << ',' << trial << ',' << n << ',' << ns << ',' << sched_getcpu() << '\n';
    }
    return schedule.eof() && !batches.empty() ? 0 : 1;
}
