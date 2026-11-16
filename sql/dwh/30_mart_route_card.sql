-- Параметры: %(as_of)s
-- Полная идемпотентная пересборка (нужна история для mom/yoy)
-- @@ clear
DELETE FROM mart.mart_route_card;
-- @@ build
INSERT INTO mart.mart_route_card (
    month_start, loading_city_gcid, unloading_city_gcid, body_group, weight_category,
    loading_city, unloading_city,
    p25_trip, median_trip, p75_trip, avg_trip, p25_km, median_km, p75_km,
    trips_count, carriers_count, cv_rate, mom_pct, yoy_pct,
    last_data_date, reliability_level, as_of)
WITH pm AS (   -- сделка x месяц (price_dates; fallback на loading_date), без плановых будущих месяцев
    SELECT price_id, date_trunc('month', d)::date AS month_start, max(d) AS last_date
    FROM (
        SELECT c.price_id, COALESCE(pd.price_date, c.loading_date) AS d
        FROM core.prices_clean c
        LEFT JOIN public.price_dates pd ON pd.price_id = c.price_id
    ) x
    WHERE d <= %(as_of)s::date
    GROUP BY price_id, date_trunc('month', d)::date
), base AS (
    SELECT pm.month_start, c.loading_city_gcid, c.unloading_city_gcid, bg.body_group,
           c.weight_category, c.price_id, c.price_rub,
           c.price_rub / NULLIF(c.distance, 0) AS price_km,
           c.organization_id, c.price_type, pm.last_date
    FROM pm
    JOIN core.prices_clean c       ON c.price_id = pm.price_id
    JOIN core.price_body_group bg  ON bg.price_id = c.price_id
    WHERE c.is_fact AND NOT c.is_complex AND NOT c.outlier_mark
      AND c.price_rub > 0 AND c.distance > 0
), agg AS (
    SELECT month_start, loading_city_gcid, unloading_city_gcid, body_group, weight_category,
           percentile_cont(0.25) WITHIN GROUP (ORDER BY price_rub) AS p25_trip,
           percentile_cont(0.50) WITHIN GROUP (ORDER BY price_rub) AS median_trip,
           percentile_cont(0.75) WITHIN GROUP (ORDER BY price_rub) AS p75_trip,
           avg(price_rub) AS avg_trip,
           percentile_cont(0.25) WITHIN GROUP (ORDER BY price_km) AS p25_km,
           percentile_cont(0.50) WITHIN GROUP (ORDER BY price_km) AS median_km,
           percentile_cont(0.75) WITHIN GROUP (ORDER BY price_km) AS p75_km,
           count(DISTINCT price_id)::int AS trips_count,
           (count(DISTINCT organization_id) FILTER (WHERE price_type IN (3, 9)))::int AS carriers_count,
           CASE WHEN count(*) >= 2 AND avg(price_rub) <> 0
                THEN stddev_samp(price_rub) / avg(price_rub) END AS cv_rate,
           max(last_date) AS last_data_date
    FROM base
    GROUP BY month_start, loading_city_gcid, unloading_city_gcid, body_group, weight_category
)
SELECT a.month_start, a.loading_city_gcid, a.unloading_city_gcid, a.body_group, a.weight_category,
       lc.city_name, uc.city_name,
       
       ROUND(a.p25_trip::numeric, 2),
       ROUND(a.median_trip::numeric, 2),
       ROUND(a.p75_trip::numeric, 2),
       ROUND(a.avg_trip::numeric, 2),
       ROUND(a.p25_km::numeric, 2),
       ROUND(a.median_km::numeric, 2),
       ROUND(a.p75_km::numeric, 2),
       a.trips_count, 
       a.carriers_count, 
       ROUND(a.cv_rate::numeric, 4),
CASE
    WHEN pm1.median_trip IS NOT NULL AND pm1.median_trip <> 0
    THEN ROUND(
        ((a.median_trip / pm1.median_trip - 1) * 100)::numeric,
        2
    )
END,

CASE
    WHEN py.median_trip IS NOT NULL AND py.median_trip <> 0
    THEN ROUND(
        ((a.median_trip / py.median_trip - 1) * 100)::numeric,
        2
    )
END,


       a.last_data_date,
       CASE WHEN a.trips_count >= 30 AND a.carriers_count >= 5
                 AND (%(as_of)s::date - a.last_data_date) <= 30 THEN 'HIGH'
            WHEN a.trips_count >= 10 THEN 'MEDIUM'
            ELSE 'LOW_DATA' END,
       %(as_of)s::date
FROM agg a
LEFT JOIN agg pm1 ON pm1.loading_city_gcid = a.loading_city_gcid
                 AND pm1.unloading_city_gcid = a.unloading_city_gcid
                 AND pm1.body_group = a.body_group AND pm1.weight_category = a.weight_category
                 AND pm1.month_start = (a.month_start - interval '1 month')::date
LEFT JOIN agg py  ON py.loading_city_gcid = a.loading_city_gcid
                 AND py.unloading_city_gcid = a.unloading_city_gcid
                 AND py.body_group = a.body_group AND py.weight_category = a.weight_category
                 AND py.month_start = (a.month_start - interval '1 year')::date
LEFT JOIN core.dim_city lc ON lc.gc_id = a.loading_city_gcid
LEFT JOIN core.dim_city uc ON uc.gc_id = a.unloading_city_gcid;
