-- Параметры: %(start_date)s, %(end_date)s, %(rub_min_price)s
-- @@ stage
CREATE TEMP TABLE stg_prices ON COMMIT DROP AS
WITH fx AS (
    SELECT num_code::text AS num_code, setting_date, avg(value) AS rate
    FROM public.exchange_rates
    GROUP BY num_code::text, setting_date
)
SELECT
    p.id                                   AS price_id,
    p.loading_date,
    p.created_at,
    p.loading_city_gcid,
    p.unloading_city_gcid,
    p.distance,
    p.total_weight,
    p.total_volume,
    p.body_type,
    p.price_type,
    (p.price_type IN (1, 2, 3, 4, 5, 9))   AS is_fact,
    COALESCE(p."complex", false)           AS is_complex,
    p.organization_id,
    p.currency_code,
    p.nearest_rate_date,
    p.price                                AS price_orig,
    CASE WHEN p.currency_code::integer = 643 THEN ROUND(p.price::numeric, 2)
         ELSE ROUND((p.price * fx.rate)::numeric, 2) END AS price_rub,
    COALESCE(p.outlier_mark, false)        AS outlier_mark,
    COALESCE(
        NULLIF(btrim(p.weight_category::text), ''),
        CASE
            WHEN ROUND(p.total_weight::numeric, 1) >= 30  THEN 'G20T'
            WHEN ROUND(p.total_weight::numeric, 1) >= 10  THEN 'FTL'
            WHEN ROUND(p.total_weight::numeric, 1) >= 5   THEN '10T'
            WHEN ROUND(p.total_weight::numeric, 1) >= 2.5 THEN '5T'
            WHEN ROUND(p.total_weight::numeric, 1) >= 0.5 THEN 'L5T'
            ELSE 'OTH'
        END)                               AS weight_category,
    COALESCE(
        NULLIF(btrim(p.volume_category::text), ''),
        CASE WHEN p.total_volume > 0 AND p.total_volume <= 120 THEN 'FTL' ELSE 'OTH' END
    )                                      AS volume_category,
    CASE
        WHEN p.price IS NULL OR p.price <= 0                              THEN 'PRICE_NON_POSITIVE'
        WHEN p.currency_code::integer = 643 AND p.price <= %(rub_min_price)s       THEN 'RUB_PRICE_OUT_OF_RANGE'
        WHEN p.distance IS NULL OR p.distance <= 0                        THEN 'DISTANCE_INVALID'
        WHEN p.total_weight < 0                                           THEN 'NEGATIVE_WEIGHT'
        WHEN p.total_volume < 0                                           THEN 'NEGATIVE_VOLUME'
        WHEN lc.gc_id IS NULL OR uc.gc_id IS NULL                         THEN 'CITY_NOT_FOUND'
        WHEN p.currency_code IS NULL
             OR p.currency_code::integer NOT IN (643, 840, 978)                    THEN 'UNKNOWN_CURRENCY'
        WHEN p.currency_code::integer <> 643 AND fx.rate IS NULL                   THEN 'FX_RATE_MISSING'
    END                                    AS dq_reason
FROM public.prices p
LEFT JOIN core.dim_city lc ON lc.gc_id = p.loading_city_gcid
LEFT JOIN core.dim_city uc ON uc.gc_id = p.unloading_city_gcid
LEFT JOIN fx ON fx.num_code = p.currency_code::text AND fx.setting_date = p.nearest_rate_date
WHERE p.loading_date BETWEEN %(start_date)s AND %(end_date)s;
-- @@ del_body_groups
DELETE FROM core.price_body_group g
USING public.prices p
WHERE p.id = g.price_id AND p.loading_date BETWEEN %(start_date)s AND %(end_date)s;
-- @@ del_core
DELETE FROM core.prices_clean WHERE loading_date BETWEEN %(start_date)s AND %(end_date)s;
-- @@ del_quarantine
DELETE FROM core.dq_quarantine_prices WHERE loading_date BETWEEN %(start_date)s AND %(end_date)s;
-- @@ ins_core
INSERT INTO core.prices_clean (
    price_id, loading_date, created_at, loading_city_gcid, unloading_city_gcid, distance,
    total_weight, total_volume, body_type, price_type, is_fact, is_complex, organization_id,
    currency_code, nearest_rate_date, price_orig, price_rub, outlier_mark,
    weight_category, volume_category)
SELECT price_id, loading_date, created_at, loading_city_gcid, unloading_city_gcid, distance,
       total_weight, total_volume, body_type, price_type, is_fact, is_complex, organization_id,
       currency_code::integer, nearest_rate_date, price_orig, price_rub, outlier_mark,
       weight_category, volume_category
FROM stg_prices
WHERE dq_reason IS NULL;
-- @@ ins_quarantine
INSERT INTO core.dq_quarantine_prices (
    price_id, loading_date, dq_reason, price_orig, currency_code, distance,
    total_weight, total_volume, loading_city_gcid, unloading_city_gcid)
SELECT price_id, loading_date, dq_reason, price_orig, currency_code::integer, distance,
       total_weight, total_volume, loading_city_gcid, unloading_city_gcid
FROM stg_prices
WHERE dq_reason IS NOT NULL;
-- @@ ins_body_groups
WITH bt AS (
    SELECT pbt.price_id, pbt.body_type_id AS bt_id
    FROM public.price_body_types pbt
    UNION
    SELECT p.id, p.body_type
    FROM public.prices p
    WHERE p.body_type IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM public.price_body_types x WHERE x.price_id = p.id)
), mapped AS (
    SELECT price_id,
           CASE WHEN bt_id IN (56, 57, 58, 59, 60, 61) THEN 'Тент'
                WHEN bt_id IN (4, 46, 47, 48)          THEN 'Рефрижератор'
                WHEN bt_id = 2                         THEN 'Изотерм'
                WHEN bt_id IN (1, 15)                  THEN 'Борт'
                ELSE 'Прочие' END AS body_group
    FROM bt
    WHERE bt_id IS NOT NULL
)
INSERT INTO core.price_body_group (price_id, body_group, body_rank)
SELECT DISTINCT c.price_id,
       COALESCE(m.body_group, 'Не указан'),
       CASE COALESCE(m.body_group, 'Не указан')
            WHEN 'Тент' THEN 1 WHEN 'Рефрижератор' THEN 2 WHEN 'Изотерм' THEN 3
            WHEN 'Борт' THEN 4 WHEN 'Прочие' THEN 5 ELSE 6 END
FROM core.prices_clean c
LEFT JOIN mapped m ON m.price_id = c.price_id
WHERE c.loading_date BETWEEN %(start_date)s AND %(end_date)s;
