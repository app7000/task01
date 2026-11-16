-- @@ clear
DELETE FROM core.dim_city;
-- @@ load
INSERT INTO core.dim_city (gc_id, city_id, city_name, full_name_local, region_name, latitude, longitude)
SELECT DISTINCT ON (c.gc_id)
       c.gc_id,
       c.id,
       btrim(split_part(c.full_name_local, ',', 1)),
       c.full_name_local,
       CASE WHEN position(',' IN c.full_name_local) > 0
            THEN NULLIF(btrim(substring(c.full_name_local FROM position(',' IN c.full_name_local) + 1)), '') END,
       c.latitude,
       c.longitude
FROM public.cities c
WHERE c.gc_id IS NOT NULL
ORDER BY c.gc_id, c.id;
