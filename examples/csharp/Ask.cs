// Call one department tool through the gateway. Run from the repo root; needs the .NET 10 SDK (file-based app):
//   dotnet run examples/csharp/Ask.cs -- supplier-delay-triage triage-default "A storm closed the port. 2 days late."
// Exit 0 = valid reply, 1 = invalid (take the fallback path), 2 = the call failed.
// No PII masking here: mask upstream (gateway/pii.py is the reference) before sending personal data.
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

if (args.Length != 3)
{
    Console.Error.WriteLine("usage: Ask.cs <tool> <alias> <text>");
    return 2;
}
var (tool, alias, text) = (args[0], args[1], args[2]);
var dir = Path.Combine("tools", tool);
if (!Directory.Exists(dir))
{
    Console.Error.WriteLine($"unknown tool \"{tool}\"");
    return 2;
}
var prompt = File.ReadAllText(Path.Combine(dir, "prompt.md"));
var contract = JsonNode.Parse(File.ReadAllText(Path.Combine(dir, "contract.json")))!;
var url = (Environment.GetEnvironmentVariable("GATEWAY_URL") ?? "http://localhost:4000").TrimEnd('/');
var key = Environment.GetEnvironmentVariable("GATEWAY_KEY") ?? "sk-dev-only-master"; // in real use, the tool's own key

string raw;
try
{
    using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(60) };
    var body = new JsonObject
    {
        ["model"] = alias,
        ["temperature"] = 0,
        ["max_tokens"] = 400,
        ["messages"] = new JsonArray(
            new JsonObject { ["role"] = "system", ["content"] = prompt },
            new JsonObject { ["role"] = "user", ["content"] = $"<input>{text}</input>" }), // untrusted data, as the prompt says
    };
    using var req = new HttpRequestMessage(HttpMethod.Post, $"{url}/v1/chat/completions")
    {
        Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json"),
    };
    req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", key);
    var res = await http.SendAsync(req);
    res.EnsureSuccessStatusCode();
    var reply = JsonNode.Parse(await res.Content.ReadAsStringAsync())!;
    raw = reply["choices"]![0]!["message"]!["content"]?.GetValue<string>() ?? "";
}
catch (Exception e)
{
    Console.Error.WriteLine($"gateway call failed: {e.GetType().Name}");
    return 2;
}

var ok = Valid(raw, contract);
Console.WriteLine($"alias={alias} valid={ok}\n{raw}");
return ok ? 0 : 1;

static bool Valid(string raw, JsonNode contract)
{
    JsonObject? o;
    try { o = JsonNode.Parse(raw) as JsonObject; }
    catch (JsonException) { return false; }
    if (o is null) return false;

    var fields = contract["fields"]!.AsObject();
    var text = contract["text"]!.AsArray();
    if (o.Count != fields.Count + text.Count) return false; // with the checks below, this makes the key set exact

    foreach (var (k, allowed) in fields)
    {
        if (!o.TryGetPropertyValue(k, out var v) || v is not JsonValue val) return false;
        if (allowed is JsonValue a && a.TryGetValue<string>(out var kind) && kind == "bool")
        {
            if (!val.TryGetValue<bool>(out _)) return false;
        }
        else if (!val.TryGetValue<string>(out var s) || !allowed!.AsArray().Any(x => x!.GetValue<string>() == s))
        {
            return false;
        }
    }
    foreach (var k in text)
    {
        if (!o.TryGetPropertyValue(k!.GetValue<string>(), out var v)
            || v is not JsonValue val || !val.TryGetValue<string>(out var s) || s == "") return false;
    }
    return true;
}
