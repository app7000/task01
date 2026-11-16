CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS mart;

-- Дедуплицированный справочник городов: минимальный cities.id на gc_id
CREATE TABLE IF NOT EXISTS core.dim_city (
    gc_id            bigint PRIMARY KEY,
    city_id          bigint,
    city_name        text,
    full_name_local  text,
    region_name      text,
    latitude         double precision,
    longitude        double precision
);

-- Очищенные сделки (Core DWH)
CREATE TABLE IF NOT EXISTS core.prices_clean (
    price_id             bigint PRIMARY KEY,
    loading_date         date NOT NULL,
    created_at           timestamp,
    loading_city_gcid    bigint NOT NULL,
    unloading_city_gcid  bigint NOT NULL,
    distance             numeric NOT NULL,
    total_weight         numeric,
    total_volume         numeric,
    body_type            integer,
    price_type           integer,
    is_fact              boolean NOT NULL,
    is_complex           boolean NOT NULL,
    organization_id      bigint,
    currency_code        integer,
    nearest_rate_date    date,
    price_orig           numeric NOT NULL,
    price_rub            numeric NOT NULL,
    outlier_mark         boolean NOT NULL,
    weight_category      text NOT NULL,
    volume_category      text NOT NULL,
    etl_loaded_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_prices_clean_loading_date ON core.prices_clean (loading_date);

-- Карантин DQ: одна строка на сделку, первая сработавшая причина
CREATE TABLE IF NOT EXISTS core.dq_quarantine_prices (
    price_id             bigint PRIMARY KEY,
    loading_date         date,
    dq_reason            text NOT NULL,
    price_orig           numeric,
    currency_code        integer,
    distance             numeric,
    total_weight         numeric,
    total_volume         numeric,
    loading_city_gcid    bigint,
    unloading_city_gcid  bigint,
    quarantined_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_dq_loading_date ON core.dq_quarantine_prices (loading_date);

-- Сделка x группа кузова (без дублей одной цены внутри группы)
CREATE TABLE IF NOT EXISTS core.price_body_group (
    price_id    bigint NOT NULL,
    body_group  text   NOT NULL,
    body_rank   smallint NOT NULL,
    PRIMARY KEY (price_id, body_group)
);

-- Одна основная группа на сделку (для ML): наименьший body_rank
CREATE OR REPLACE VIEW core.v_price_body_group_primary AS
SELECT DISTINCT ON (price_id) price_id, body_group
FROM core.price_body_group
ORDER BY price_id, body_rank;

-- Витрина карточки маршрута / коридора ставок
CREATE TABLE IF NOT EXISTS mart.mart_route_card (
    month_start          date    NOT NULL,
    loading_city_gcid    bigint  NOT NULL,
    unloading_city_gcid  bigint  NOT NULL,
    body_group           text    NOT NULL,
    weight_category      text    NOT NULL,
    loading_city         text,
    unloading_city       text,
    p25_trip             numeric,
    median_trip          numeric,
    p75_trip             numeric,
    avg_trip             numeric,
    p25_km               numeric,
    median_km            numeric,
    p75_km               numeric,
    trips_count          integer NOT NULL,
    carriers_count       integer NOT NULL,
    cv_rate              numeric,
    mom_pct              numeric,
    yoy_pct              numeric,
    last_data_date       date,
    reliability_level    text    NOT NULL,
    as_of                date    NOT NULL,
    built_at             timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (month_start, loading_city_gcid, unloading_city_gcid, body_group, weight_category)
);
CREATE INDEX IF NOT EXISTS ix_route_card_route
    ON mart.mart_route_card (loading_city_gcid, unloading_city_gcid, month_start);

CREATE OR REPLACE VIEW mart.mart_market_corridor AS
SELECT month_start, loading_city_gcid, unloading_city_gcid, body_group, weight_category,
       p25_trip, median_trip, p75_trip, p25_km, median_km, p75_km,
       trips_count, carriers_count, reliability_level
FROM mart.mart_route_card;

-- Прогнозы
CREATE TABLE IF NOT EXISTS mart.ml_price_predictions (
    price_id             bigint NOT NULL,
    loading_date         date,
    loading_city_gcid    bigint,
    unloading_city_gcid  bigint,
    body_group           text,
    split_name           text NOT NULL,          -- 'test' | 'future'
    actual_price_rub     numeric,
    predicted_price_rub  numeric NOT NULL,
    abs_error_rub        numeric,
    ape_pct              numeric,
    model_name           text NOT NULL,
    scored_at            timestamptz NOT NULL,
    PRIMARY KEY (price_id, model_name)
);

CREATE TABLE IF NOT EXISTS mart.ml_model_metrics (
    model_name   text NOT NULL,
    as_of        date NOT NULL,
    train_start  date, train_end_excl date, test_start date, test_end date,
    n_train      integer, n_test integer,
    r2           double precision, mape_pct double precision,
    rmse_rub     double precision, mae_rub  double precision,
    trained_at   timestamptz NOT NULL,
    PRIMARY KEY (model_name, as_of)
);
