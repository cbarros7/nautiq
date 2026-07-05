CREATE TABLE IF NOT EXISTS ports (
    locode   text PRIMARY KEY,
    name     text,
    country  text,
    lat      double precision,
    lon      double precision
);

CREATE TABLE IF NOT EXISTS thetis_mrv (
    imo                 bigint PRIMARY KEY,
    name                text,
    ship_type           text,
    dwt                 numeric,
    gt                  numeric,
    eexi                numeric,
    annual_fuel_t       numeric,
    annual_distance_nm  numeric,
    annual_co2_t        numeric,
    loaded_at           timestamptz DEFAULT now()
);
