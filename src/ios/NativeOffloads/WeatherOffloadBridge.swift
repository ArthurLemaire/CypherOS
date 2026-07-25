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
