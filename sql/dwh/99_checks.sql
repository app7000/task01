-- Примеры проверочных запросов
-- 1. Отсев DQ по причинам
SELECT dq_reason, count(*) FROM core.dq_quarantine_prices GROUP BY 1 ORDER BY 2 DESC;
-- 2. Баланс: источник = core + карантин
SELECT (SELECT count(*) FROM public.prices) AS src,
       (SELECT count(*) FROM core.prices_clean) AS clean,
       (SELECT count(*) FROM core.dq_quarantine_prices) AS quarantine;
-- 3. Коридор по самым плотным маршрутам
SELECT * FROM mart.mart_route_card ORDER BY trips_count DESC LIMIT 20;
-- 4. Распределение надёжности
SELECT reliability_level, count(*) FROM mart.mart_route_card GROUP BY 1;
-- 5. Факт vs прогноз
SELECT split_name, count(*), round(avg(ape_pct), 2) AS mape FROM mart.ml_price_predictions GROUP BY 1;
-- 6. Будущие заявки: факт должен быть NULL
SELECT count(*) FROM mart.ml_price_predictions WHERE split_name = 'future' AND actual_price_rub IS NOT NULL;
-- 7. Метрики моделей
SELECT * FROM mart.ml_model_metrics;
