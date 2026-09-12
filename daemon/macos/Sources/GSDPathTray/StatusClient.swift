import Foundation

enum FetchError: Error {
    case badURL
    case transport(Error)
    case badStatus(Int)
    case serverError(String)
    case decode(Error)
}

/// Human-presentable rendering, used by alert dialogs.
func describe(_ error: FetchError) -> String {
    switch error {
    case .serverError(let message): return message
    case .transport(let e): return e.localizedDescription
    case .badStatus(let code): return "Daemon replied with HTTP \(code)."
    case .badURL: return "Bad URL."
    case .decode: return "Unexpected response from the daemon."
    }
}

/// Fetches and decodes the daemon status JSON. The completion handler runs on a
/// background queue; callers dispatch to the main thread for UI work.
func fetchStatus(url: URL, timeout: TimeInterval = 3,
                 completion: @escaping (Result<StatusResponse, FetchError>) -> Void) {
    var request = URLRequest(url: url)
    request.timeoutInterval = timeout
    request.cachePolicy = .reloadIgnoringLocalCacheData
    URLSession.shared.dataTask(with: request) { data, response, error in
        if let error = error {
            completion(.failure(.transport(error)))
            return
        }
        if let http = response as? HTTPURLResponse, http.statusCode != 200 {
            completion(.failure(.badStatus(http.statusCode)))
            return
        }
        guard let data = data else {
            completion(.failure(.transport(URLError(.badServerResponse))))
            return
        }
        do {
            let status = try JSONDecoder().decode(StatusResponse.self, from: data)
            completion(.success(status))
        } catch {
            completion(.failure(.decode(error)))
        }
    }.resume()
}

/// POSTs a watched-parent add/remove action to the daemon config API. On a
/// non-200 reply the server's `{"error": ...}` message is surfaced when present.
/// The completion handler runs on a background queue; callers dispatch to the
/// main thread for UI work.
func postParentAction(url: URL, action: String, path: String, timeout: TimeInterval = 3,
                      completion: @escaping (Result<Void, FetchError>) -> Void) {
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.timeoutInterval = timeout
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.httpBody = try? JSONSerialization.data(withJSONObject: ["action": action, "path": path])
    URLSession.shared.dataTask(with: request) { data, response, error in
        if let error = error {
            completion(.failure(.transport(error)))
            return
        }
        if let http = response as? HTTPURLResponse, http.statusCode != 200 {
            if let data = data,
               let body = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let message = body["error"] as? String {
                completion(.failure(.serverError(message)))
            } else {
                completion(.failure(.badStatus(http.statusCode)))
            }
            return
        }
        completion(.success(()))
    }.resume()
}
