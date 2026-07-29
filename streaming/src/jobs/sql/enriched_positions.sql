CREATE TEMPORARY VIEW enriched_positions AS
SELECT *,
    3440.065 * ACOS(
        CASE 
            WHEN (SIN(RADIANS(prev_lat)) * SIN(RADIANS(lat)) + COS(RADIANS(prev_lat)) * COS(RADIANS(lat)) * COS(RADIANS(lon - prev_lon))) > 1.0 THEN 1.0
            WHEN (SIN(RADIANS(prev_lat)) * SIN(RADIANS(lat)) + COS(RADIANS(prev_lat)) * COS(RADIANS(lat)) * COS(RADIANS(lon - prev_lon))) < -1.0 THEN -1.0
            ELSE (SIN(RADIANS(prev_lat)) * SIN(RADIANS(lat)) + COS(RADIANS(prev_lat)) * COS(RADIANS(lat)) * COS(RADIANS(lon - prev_lon)))
        END
    ) AS distance_nm,
    CAST(TIMESTAMPDIFF(SECOND, prev_time, event_time) AS DOUBLE) / 3600.0 AS delta_hours
FROM (
    SELECT *,
        LAG(lat) OVER w AS prev_lat,
        LAG(lon) OVER w AS prev_lon,
        LAG(event_time) OVER w AS prev_time
    FROM PositionsKafka
    WINDOW w AS (PARTITION BY mmsi ORDER BY event_time)
)
