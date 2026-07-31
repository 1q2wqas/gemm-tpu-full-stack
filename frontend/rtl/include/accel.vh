`ifndef ACCEL_VH
`define ACCEL_VH

// Builds may override the matrix shape and array size from the simulator command line.
`ifndef ACCEL_TM
`define ACCEL_TM 8
`endif

`ifndef ACCEL_TN
`define ACCEL_TN 8
`endif

`ifndef ACCEL_K_MAX
`define ACCEL_K_MAX 8
`endif

`ifndef ACCEL_P
`define ACCEL_P 4
`endif

`ifndef ACCEL_A_W
`define ACCEL_A_W 8
`endif

`ifndef ACCEL_B_W
`define ACCEL_B_W 8
`endif

// INT8 products accumulate in a signed 32-bit lane by default.
`ifndef ACCEL_PSUM_W
`define ACCEL_PSUM_W 32
`endif

`ifndef ACCEL_PROD_W
`define ACCEL_PROD_W (`ACCEL_A_W + `ACCEL_B_W)
`endif

`define ACCEL_CLOG2(x) \
    ((x) <= 2      ? 1  : \
     (x) <= 4      ? 2  : \
     (x) <= 8      ? 3  : \
     (x) <= 16     ? 4  : \
     (x) <= 32     ? 5  : \
     (x) <= 64     ? 6  : \
     (x) <= 128    ? 7  : \
     (x) <= 256    ? 8  : \
     (x) <= 512    ? 9  : \
     (x) <= 1024   ? 10 : \
     (x) <= 2048   ? 11 : \
     (x) <= 4096   ? 12 : \
     (x) <= 8192   ? 13 : \
     (x) <= 16384  ? 14 : \
     (x) <= 32768  ? 15 : \
     16)

// Matrices are stored as flat row-major memories.
`define ACCEL_A_DEPTH (`ACCEL_TM * `ACCEL_K_MAX)
`define ACCEL_B_DEPTH (`ACCEL_K_MAX * `ACCEL_TN)
`define ACCEL_C_DEPTH (`ACCEL_TM * `ACCEL_TN)

`ifndef ACCEL_A_ADDR_W
`define ACCEL_A_ADDR_W (`ACCEL_CLOG2(`ACCEL_A_DEPTH))
`endif

`ifndef ACCEL_B_ADDR_W
`define ACCEL_B_ADDR_W (`ACCEL_CLOG2(`ACCEL_B_DEPTH))
`endif

`ifndef ACCEL_C_ADDR_W
`define ACCEL_C_ADDR_W (`ACCEL_CLOG2(`ACCEL_C_DEPTH))
`endif

`ifndef ACCEL_M_W
`define ACCEL_M_W (`ACCEL_CLOG2(`ACCEL_TM))
`endif

`ifndef ACCEL_N_W
`define ACCEL_N_W (`ACCEL_CLOG2(`ACCEL_TN))
`endif

`ifndef ACCEL_K_W
`define ACCEL_K_W (`ACCEL_CLOG2(`ACCEL_K_MAX))
`endif

`ifndef ACCEL_ROW_OFF_W
`define ACCEL_ROW_OFF_W (`ACCEL_CLOG2(`ACCEL_P))
`endif

// A wavefront needs P-1 cycles to cross either edge of the array.
`define ACCEL_SYSTOLIC_FILL   ((`ACCEL_P) - 1)
`define ACCEL_SYSTOLIC_DRAIN  ((`ACCEL_P) - 1)

`define ACCEL_MAC_CYCLES      ((`ACCEL_K_MAX) + 2*((`ACCEL_P) - 1) + 1)

`define ACCEL_UNLOAD_CYCLES   (`ACCEL_P)

`ifndef ACCEL_MAC_T_W
`define ACCEL_MAC_T_W (`ACCEL_CLOG2(`ACCEL_MAC_CYCLES))
`endif

`ifndef ACCEL_UNLOAD_T_W
`define ACCEL_UNLOAD_T_W (`ACCEL_CLOG2(`ACCEL_UNLOAD_CYCLES))
`endif

// Flat buses pack lane 0 in the least-significant slice.
`define ACCEL_A_RD_ADDR_FLAT_W (`ACCEL_P * `ACCEL_A_ADDR_W)
`define ACCEL_B_RD_ADDR_FLAT_W (`ACCEL_P * `ACCEL_B_ADDR_W)

`define ACCEL_A_RD_DATA_FLAT_W (`ACCEL_P * `ACCEL_A_W)
`define ACCEL_B_RD_DATA_FLAT_W (`ACCEL_P * `ACCEL_B_W)

`define ACCEL_A_VEC_W (`ACCEL_P * `ACCEL_A_W)
`define ACCEL_B_VEC_W (`ACCEL_P * `ACCEL_B_W)

`define ACCEL_PSUM_FLAT_W (`ACCEL_P * `ACCEL_P * `ACCEL_PSUM_W)

`define ACCEL_PSUM_ROW_FLAT_W (`ACCEL_P * `ACCEL_PSUM_W)

`define ACCEL_C_ROW_FLAT_W (`ACCEL_P * `ACCEL_PSUM_W)

`define ACCEL_LANE(bus, i, w)        (bus[((i)*(w)) +: (w)])

`define ACCEL_A_ADDR_LANE(bus, i)    (bus[((i)*`ACCEL_A_ADDR_W) +: `ACCEL_A_ADDR_W])
`define ACCEL_B_ADDR_LANE(bus, i)    (bus[((i)*`ACCEL_B_ADDR_W) +: `ACCEL_B_ADDR_W])

`define ACCEL_A_DATA_LANE(bus, i)    (bus[((i)*`ACCEL_A_W) +: `ACCEL_A_W])
`define ACCEL_B_DATA_LANE(bus, i)    (bus[((i)*`ACCEL_B_W) +: `ACCEL_B_W])

// Full-array psums use row-major lane numbering: i*P+j.
`define ACCEL_PSUM_LANE(bus, i, j)   (bus[(((i)*`ACCEL_P + (j))*`ACCEL_PSUM_W) +: `ACCEL_PSUM_W])

`define ACCEL_PSUM_ROW_LANE(bus, j)  (bus[((j)*`ACCEL_PSUM_W) +: `ACCEL_PSUM_W])

// Keep address formulas shared between the RTL variants and testbench.
`define ACCEL_ADDR_A(m, k)  (((m) * (`ACCEL_K_MAX)) + (k))
`define ACCEL_ADDR_B(k, n)  (((k) * (`ACCEL_TN))    + (n))
`define ACCEL_ADDR_C(m, n)  (((m) * (`ACCEL_TN))    + (n))

`define ACCEL_SEXT(val, in_w, out_w)  ({{((out_w)-(in_w)){val[(in_w)-1]}}, (val)})

`define ACCEL_PROD_TO_PSUM(x)         `ACCEL_SEXT(x, `ACCEL_PROD_W, `ACCEL_PSUM_W)

`define ACCEL_SEXT16_TO32(x)          ({{16{x[15]}}, (x)})

`endif

`ifndef MPRJ_IO_PADS
`define MPRJ_IO_PADS 38
`endif
