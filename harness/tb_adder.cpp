// Verilator testbench for approx_adder: golden-reference NMED computation.
// Compile: verilator --cc approx_adder.v --exe tb_adder.cpp -o sim && make -C obj_dir -f Vapprox_adder.mk
// Run: ./obj_dir/Vapprox_adder <ADDER_LENGTH> [num_samples: 0=exhaustive for 8-bit]
#include <iostream>
#include <fstream>
#include <vector>
#include <cmath>
#include <cstdlib>
#include "Vapprox_adder.h"
#include "verilated.h"

int main(int argc, char** argv) {
    int ADDER_LENGTH = 8;
    int num_samples = 0;  // 0 = exhaustive for 8-bit, else stratified random
    if (argc >= 2) ADDER_LENGTH = atoi(argv[1]);
    if (argc >= 3) num_samples = atoi(argv[2]);

    Verilated::commandArgs(argc, argv);
    Vapprox_adder* top = new Vapprox_adder;

    int imprecise_part = ADDER_LENGTH / 4;  // default 25% approximate
    if (imprecise_part < 1) imprecise_part = 1;

    uint64_t max_val = (1ULL << ADDER_LENGTH);
    uint64_t n_tests = num_samples > 0 ? (uint64_t)num_samples : (ADDER_LENGTH <= 8 ? max_val * max_val : 100000);
    if (n_tests > 5000000) n_tests = 5000000;

    double sum_abs_err = 0;
    double sum_exact = 0;
    int64_t max_abs_err = 0;
    uint64_t count = 0;

    for (uint64_t i = 0; i < n_tests; i++) {
        uint64_t a_val, b_val;
        if (num_samples == 0 && ADDER_LENGTH <= 8) {
            a_val = i / max_val;
            b_val = i % max_val;
        } else {
            a_val = rand() % max_val;
            b_val = rand() % max_val;
        }
        uint32_t a32 = (uint32_t)(a_val & ((1ULL << ADDER_LENGTH) - 1));
        uint32_t b32 = (uint32_t)(b_val & ((1ULL << ADDER_LENGTH) - 1));
        top->a = a32;
        top->b = b32;
        top->eval();
        uint32_t sum_approx = (uint32_t)(top->sum & ((1ULL << (ADDER_LENGTH + 1)) - 1));
        uint64_t exact = (uint64_t)a32 + (uint64_t)b32;
        int64_t err = (int64_t)sum_approx - (int64_t)exact;
        if (err < 0) err = -err;
        if ((uint64_t)err > (uint64_t)max_abs_err) max_abs_err = (int64_t)err;
        sum_abs_err += (double)err;
        sum_exact += (double)exact;
        count++;
    }

    double med_avg = sum_abs_err / (double)count;
    double avg_exact = sum_exact / (double)count;
    double nmed = (avg_exact != 0) ? (med_avg / fabs(avg_exact)) : med_avg;

    std::cout << "NMED=" << nmed << " MED_avg=" << med_avg << " max_abs_err=" << max_abs_err
              << " count=" << count << " ADDER_LENGTH=" << ADDER_LENGTH << std::endl;
    delete top;
    return 0;
}
