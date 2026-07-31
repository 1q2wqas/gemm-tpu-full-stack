`ifndef ACCEL_VH
`define ACCEL_VH

// Standalone defaults for the broadcast prototype; the shared header is used elsewhere.
`define ACCEL_TM 8
`define ACCEL_TN 8

`ifndef ACCEL_K_MAX
`define ACCEL_K_MAX 8
`endif

`ifndef ACCEL_P
`define ACCEL_P 4
`endif

`define ACCEL_A_W     8
`define ACCEL_B_W     8
`define ACCEL_PSUM_W  32
`define ACCEL_PROD_W  16

`define ACCEL_A_DEPTH (`ACCEL_TM * `ACCEL_K_MAX)
`define ACCEL_B_DEPTH (`ACCEL_K_MAX * `ACCEL_TN)
`define ACCEL_C_DEPTH (`ACCEL_TM * `ACCEL_TN)

`define ACCEL_A_ADDR_W 6
`define ACCEL_B_ADDR_W 6
`define ACCEL_C_ADDR_W 6

// Read ports are flattened as P adjacent address/data lanes.
`define ACCEL_A_RD_ADDR_FLAT_W (`ACCEL_P * `ACCEL_A_ADDR_W)
`define ACCEL_B_RD_ADDR_FLAT_W (`ACCEL_P * `ACCEL_B_ADDR_W)

`define ACCEL_A_RD_DATA_FLAT_W (`ACCEL_P * `ACCEL_A_W)
`define ACCEL_B_RD_DATA_FLAT_W (`ACCEL_P * `ACCEL_B_W)

`define ACCEL_PSUM_FLAT_W      (`ACCEL_P * `ACCEL_P * `ACCEL_PSUM_W)

`define ACCEL_LANE(bus, i, w)        (bus[((i)*(w)) +: (w)])

`define ACCEL_A_ADDR_LANE(bus, i)    (bus[((i)*`ACCEL_A_ADDR_W) +: `ACCEL_A_ADDR_W])
`define ACCEL_B_ADDR_LANE(bus, i)    (bus[((i)*`ACCEL_B_ADDR_W) +: `ACCEL_B_ADDR_W])

`define ACCEL_A_DATA_LANE(bus, i)    (bus[((i)*`ACCEL_A_W) +: `ACCEL_A_W])
`define ACCEL_B_DATA_LANE(bus, i)    (bus[((i)*`ACCEL_B_W) +: `ACCEL_B_W])

// Accumulator lane (i,j) is stored at row-major index i*P+j.
`define ACCEL_PSUM_LANE(bus, i, j)   (bus[(((i)*`ACCEL_P + (j))*`ACCEL_PSUM_W) +: `ACCEL_PSUM_W])

`define ACCEL_SEXT16_TO32(x)         ({{16{(x)[15]}}, (x)})

`endif
