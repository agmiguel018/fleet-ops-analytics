-- KPI queries for the fleet (DuckDB), over the anonymized tables in data/anonymized/.
-- The notebook registers each CSV as a view with the same name (daily, trips, costs, odometer, vehicles, drivers).
-- Each query starts with "-- name: <id>".

-- name: availability
-- Working days = calendar days minus contractual rest days. Availability = operated / working days.
SELECT
    vehicle_id,
    COUNT(*)                                                   AS calendar_days,
    COUNT(*) FILTER (WHERE status <> 'rest_day')               AS working_days,
    COUNT(*) FILTER (WHERE status = 'operated')                AS operated_days,
    ROUND(COUNT(*) FILTER (WHERE status = 'operated')
          / COUNT(*) FILTER (WHERE status <> 'rest_day'), 3)   AS availability
FROM daily
GROUP BY vehicle_id
ORDER BY vehicle_id;

-- name: downtime_cost
-- Revenue lost on working days without operation, valued at the vehicle's average net revenue
-- per operated day (days between drivers have no driver, so the vehicle is the unit).
WITH avg_day AS (
    SELECT vehicle_id, AVG(net_revenue_aoa) AS avg_net_per_day
    FROM daily
    WHERE status = 'operated'
    GROUP BY vehicle_id
)
SELECT
    d.vehicle_id,
    d.status                                 AS cause,
    COUNT(*)                                 AS lost_days,
    ROUND(COUNT(*) * a.avg_net_per_day)      AS lost_revenue_aoa
FROM daily d
JOIN avg_day a USING (vehicle_id)
WHERE d.status NOT IN ('operated', 'rest_day')
GROUP BY d.vehicle_id, d.status, a.avg_net_per_day
ORDER BY lost_revenue_aoa DESC;

-- name: driver_productivity
-- One row per driver (each driver = one vehicle and one platform in this dataset).
SELECT
    d.driver_id,
    d.vehicle_id,
    d.platform,
    COUNT(*)                                                           AS operated_days,
    ROUND(AVG(d.trips), 1)                                             AS trips_per_day,
    ROUND(AVG(d.net_revenue_aoa))                                      AS net_per_day_aoa,
    ROUND(SUM(d.net_revenue_aoa) / SUM(d.trips))                       AS net_per_trip_aoa,
    ROUND(SUM(d.platform_fees_aoa) / SUM(d.gross_fares_aoa + d.bonus_aoa), 3) AS platform_fee_rate,
    ROUND(AVG((HOUR(CAST(d.last_trip AS TIME)) * 60 + MINUTE(CAST(d.last_trip AS TIME))
             - HOUR(CAST(d.first_trip AS TIME)) * 60 - MINUTE(CAST(d.first_trip AS TIME))) / 60), 1)
                                                                       AS avg_span_first_to_last_trip_h
FROM daily d
WHERE d.status = 'operated' AND NOT d.data_gap
GROUP BY d.driver_id, d.vehicle_id, d.platform
ORDER BY d.driver_id;

-- name: unit_economics
-- Revenue and every cost line per vehicle over its observed period, with margin.
WITH rev AS (
    SELECT vehicle_id, COUNT(*) AS calendar_days,
           SUM(net_revenue_aoa) AS net_revenue, SUM(fuel_aoa) AS fuel, SUM(wash_aoa) AS wash_daily
    FROM daily GROUP BY vehicle_id
),
cst AS (
    SELECT vehicle_id,
           SUM(amount_aoa) FILTER (WHERE category = 'maintenance')   AS maintenance,
           SUM(amount_aoa) FILTER (WHERE category = 'driver_salary') AS driver_salary,
           SUM(amount_aoa) FILTER (WHERE category = 'wash')          AS wash,
           SUM(amount_aoa) FILTER (WHERE category = 'parking')       AS parking,
           SUM(amount_aoa) FILTER (WHERE category = 'equipment')     AS equipment
    FROM costs GROUP BY vehicle_id
)
SELECT
    r.vehicle_id,
    r.calendar_days,
    ROUND(r.net_revenue)                                                    AS net_revenue,
    ROUND(r.fuel)                                                           AS fuel,
    ROUND(COALESCE(c.maintenance, 0))                                       AS maintenance,
    ROUND(COALESCE(c.driver_salary, 0))                                     AS driver_salary,
    ROUND(COALESCE(c.wash, 0) + r.wash_daily + COALESCE(c.parking, 0))      AS wash_and_parking,
    ROUND(COALESCE(c.equipment, 0))                                         AS equipment,
    ROUND(r.net_revenue - r.fuel - r.wash_daily
          - COALESCE(c.maintenance, 0) - COALESCE(c.driver_salary, 0)
          - COALESCE(c.wash, 0) - COALESCE(c.parking, 0) - COALESCE(c.equipment, 0)) AS margin,
    ROUND((r.net_revenue - r.fuel - r.wash_daily
          - COALESCE(c.maintenance, 0) - COALESCE(c.driver_salary, 0)
          - COALESCE(c.wash, 0) - COALESCE(c.parking, 0) - COALESCE(c.equipment, 0))
          / r.net_revenue, 3)                                               AS margin_rate
FROM rev r
LEFT JOIN cst c USING (vehicle_id)
ORDER BY r.vehicle_id;

-- name: odometer_intervals
-- Km, operated days, revenue and fuel cost between consecutive odometer readings.
-- Readings are taken before the day's work (Sunday inspection or vehicle handover), so an
-- interval covers [from_date, to_date). fuel_per_km is only meaningful where fuel receipts are complete.
WITH readings AS (
    SELECT vehicle_id, date, odometer_km,
           LAG(date)        OVER (PARTITION BY vehicle_id ORDER BY date) AS prev_date,
           LAG(odometer_km) OVER (PARTITION BY vehicle_id ORDER BY date) AS prev_km
    FROM odometer
)
SELECT
    r.vehicle_id,
    r.prev_date                                                        AS from_date,
    r.date                                                             AS to_date,
    r.odometer_km - r.prev_km                                          AS km,
    COUNT(d.date) FILTER (WHERE d.status = 'operated')                 AS operated_days,
    ROUND(SUM(d.net_revenue_aoa))                                      AS net_revenue,
    ROUND(SUM(d.fuel_aoa))                                             AS fuel_aoa,
    ROUND(SUM(d.fuel_aoa) / (r.odometer_km - r.prev_km), 1)            AS fuel_per_km,
    ROUND(SUM(d.net_revenue_aoa) / (r.odometer_km - r.prev_km), 1)    AS revenue_per_km
FROM readings r
LEFT JOIN daily d
       ON d.vehicle_id = r.vehicle_id AND d.date >= r.prev_date AND d.date < r.date
WHERE r.prev_date IS NOT NULL
GROUP BY r.vehicle_id, r.prev_date, r.date, r.odometer_km, r.prev_km
ORDER BY r.vehicle_id, r.date;

-- name: revenue_by_hour
-- Trips and revenue by hour of the day (trip start time).
SELECT
    vehicle_id,
    HOUR(CAST(start_time AS TIME))             AS hour,
    COUNT(*)                                   AS trips,
    ROUND(SUM(net_value_aoa))                  AS net_revenue,
    ROUND(AVG(net_value_aoa))                  AS avg_ticket
FROM trips
GROUP BY ALL
ORDER BY vehicle_id, hour;

-- name: weekly_settlement
-- Weekly net revenue minus fuel vs the contractual weekly minimum (weekly-minimum drivers only).
-- Weeks start on Monday (Sunday is the contractual rest day). Partial weeks are not pro-rated.
SELECT
    d.driver_id,
    DATE_TRUNC('week', d.date)                                AS week_start,
    COUNT(*) FILTER (WHERE d.status = 'operated')             AS operated_days,
    ROUND(SUM(d.net_revenue_aoa - d.fuel_aoa))                AS net_after_fuel,
    drivers.weekly_minimum_aoa                                AS weekly_minimum,
    ROUND(SUM(d.net_revenue_aoa - d.fuel_aoa) - drivers.weekly_minimum_aoa) AS vs_minimum
FROM daily d
JOIN drivers USING (driver_id)
WHERE drivers.settlement_model = 'weekly_minimum'
GROUP BY ALL
ORDER BY d.driver_id, week_start;
