//
//  WeatherOffloadBridge.swift
//  MinisApp
//
//  Swift bridge for WeatherKit, called from WeatherOffload.m.
//  WeatherKit is Swift-only; this class exposes weather data as NSDictionary
//  for the ObjC handler to consume.
//

import Foundation
import WeatherKit
import CoreLocation

@objc public class WeatherOffloadBridge: NSObject {

    @objc public static func fetchWeather(
        forLatitude lat: Double,
        longitude lng: Double,
        completion: @escaping (NSDictionary?, Error?) -> Void
    ) {
        let location = CLLocation(latitude: lat, longitude: lng)
        let service = WeatherService.shared

        Task {
            do {
                let weather = try await service.weather(for: location)
                let result = NSMutableDictionary()

                // Current weather
                let current = weather.currentWeather
                result["current"] = [
                    "condition": current.condition.description,
                    "temperature_c": current.temperature.converted(to: .celsius).value,
                    "apparent_temperature_c": current.apparentTemperature.converted(to: .celsius).value,
                    "humidity": current.humidity,
                    "wind_speed_kmh": current.wind.speed.converted(to: .kilometersPerHour).value,
                    "wind_direction": current.wind.compassDirection.description,
                    "pressure_hpa": current.pressure.converted(to: .hectopascals).value,
                    "pressure_trend": current.pressureTrend.description,
                    "uv_index": current.uvIndex.value,
                    "visibility_km": current.visibility.converted(to: .kilometers).value,
                    "dew_point_c": current.dewPoint.converted(to: .celsius).value,
                    "cloud_cover": current.cloudCover,
                    "is_daylight": current.isDaylight,
                    "location": ["latitude": lat, "longitude": lng],
                ] as [String: Any]

                // Hourly forecast (next 48 hours)
                let hourlyForecasts = weather.hourlyForecast.forecast
                var hourly: [[String: Any]] = []
                let dateFormatter = DateFormatter()
                dateFormatter.dateFormat = "HH:mm"
                dateFormatter.timeZone = TimeZone.current

                for forecast in hourlyForecasts.prefix(48) {
                    hourly.append([
                        "hour": dateFormatter.string(from: forecast.date),
                        "date": ISO8601DateFormatter().string(from: forecast.date),
                        "condition": forecast.condition.description,
                        "temp_c": forecast.temperature.converted(to: .celsius).value,
                        "apparent_temp_c": forecast.apparentTemperature.converted(to: .celsius).value,
                        "humidity": forecast.humidity,
                        "precip_chance": forecast.precipitationChance,
                        "wind_speed_kmh": forecast.wind.speed.converted(to: .kilometersPerHour).value,
                        "uv_index": forecast.uvIndex.value,
                        "cloud_cover": forecast.cloudCover,
                        "is_daylight": forecast.isDaylight,
                    ])
                }
                result["hourly"] = hourly

                // Daily forecast (next 10 days)
                let dailyForecasts = weather.dailyForecast.forecast
                var daily: [[String: Any]] = []
                let dayFormatter = DateFormatter()
                dayFormatter.dateFormat = "yyyy-MM-dd"
                let timeFormatter = DateFormatter()
                timeFormatter.dateFormat = "HH:mm"
                timeFormatter.timeZone = TimeZone.current

                for forecast in dailyForecasts.prefix(10) {
                    var entry: [String: Any] = [
                        "date": dayFormatter.string(from: forecast.date),
                        "condition": forecast.condition.description,
                        "high_c": forecast.highTemperature.converted(to: .celsius).value,
                        "low_c": forecast.lowTemperature.converted(to: .celsius).value,
                        "precip_chance": forecast.precipitationChance,
                        "wind_speed_kmh": forecast.wind.speed.converted(to: .kilometersPerHour).value,
                        "uv_index": forecast.uvIndex.value,
                    ]
                    if let sunrise = forecast.sun.sunrise {
                        entry["sunrise"] = timeFormatter.string(from: sunrise)
                    }
                    if let sunset = forecast.sun.sunset {
                        entry["sunset"] = timeFormatter.string(from: sunset)
                    }
                    daily.append(entry)
                }
                result["daily"] = daily

                // [T-weather-minute-precip] Minute-by-minute precipitation for
                // the next hour — the "is it about to rain?" dataset.
                //
                // `minuteForecast` is OPTIONAL for two independent reasons, and
                // both are reported rather than silently emitted as an empty
                // array: WeatherKit only produces it where minute data exists
                // (broadly: US/UK/Ireland and a few others — notably NOT
                // mainland China), and it also disappears when there is simply
                // no precipitation expected. Callers get `available: false`
                // plus a reason instead of an empty list they'd misread as
                // "definitely no rain".
                if let minute = weather.minuteForecast {
                    var minutes: [[String: Any]] = []
                    for entry in minute.forecast {
                        minutes.append([
                            "date": ISO8601DateFormatter().string(from: entry.date),
                            "minute": timeFormatter.string(from: entry.date),
                            // Probability 0…1 that precipitation falls in this minute.
                            "precip_chance": entry.precipitationChance,
                            // Intensity in mm/hr; 0 when nothing is falling.
                            // WeatherKit types rainfall rate as UnitSpeed (a
                            // length over time), so convert to m/s and scale to
                            // millimetres per hour: m/s × 1000 mm/m × 3600 s/h.
                            "precip_intensity_mmh": entry.precipitationIntensity
                                .converted(to: .metersPerSecond).value * 3_600_000,
                        ])
                    }
                    result["minute"] = [
                        "available": true,
                        "summary": minute.summary.description,
                        "minutes": minutes,
                    ] as [String: Any]
                } else {
                    result["minute"] = [
                        "available": false,
                        "reason": "WeatherKit has no minute-by-minute precipitation for this "
                                + "location right now. Minute data covers only some regions "
                                + "(not mainland China), and is also omitted when no "
                                + "precipitation is expected. Use `hourly` for precipitation "
                                + "chance by hour.",
                        "minutes": [] as [[String: Any]],
                    ] as [String: Any]
                }

                // Weather alerts
                if let alerts = weather.weatherAlerts {
                    var alertList: [[String: Any]] = []
                    for alert in alerts {
                        alertList.append([
                            "summary": alert.summary,
                            "severity": alert.severity.description,
                            "source": alert.source,
                            "region": alert.region ?? "",
                        ])
                    }
                    result["alerts"] = alertList
                } else {
                    result["alerts"] = [] as [[String: Any]]
                }

                completion(result, nil)
            } catch {
                completion(nil, error)
            }
        }
    }
}
