// Call one department tool through the gateway. Run from the repo root, standard library only:
//
//	go run examples/go/ask.go supplier-delay-triage triage-default "A storm closed the port. 2 days late."
//
// Exit 0 = valid reply, 1 = invalid (take the fallback path), 2 = the call failed.
// No PII masking here: mask upstream (gateway/pii.py is the reference) before sending personal data.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type contract struct {
	Fields map[string]any `json:"fields"` // a list of allowed strings, or "bool"
	Text   []string       `json:"text"`
}

func env(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}

func fail(code int, format string, a ...any) {
	fmt.Fprintf(os.Stderr, format+"\n", a...)
	os.Exit(code)
}

func valid(raw string, c contract) bool {
	var out map[string]any
	if json.Unmarshal([]byte(raw), &out) != nil || len(out) != len(c.Fields)+len(c.Text) {
		return false // not an object, or the key set cannot match
	}
	for k, allowed := range c.Fields {
		v, present := out[k]
		if !present {
			return false
		}
		if allowed == "bool" {
			if _, ok := v.(bool); !ok {
				return false
			}
			continue
		}
		s, isString := v.(string)
		found := false
		list, _ := allowed.([]any)
		for _, a := range list {
			found = found || (isString && a == s)
		}
		if !found {
			return false
		}
	}
	for _, k := range c.Text {
		if s, ok := out[k].(string); !ok || s == "" {
			return false
		}
	}
	return true
}

func main() {
	if len(os.Args) != 4 {
		fail(2, "usage: go run examples/go/ask.go <tool> <alias> <text>")
	}
	tool, alias, text := os.Args[1], os.Args[2], os.Args[3]
	dir := filepath.Join("tools", tool)
	prompt, err := os.ReadFile(filepath.Join(dir, "prompt.md"))
	if err != nil {
		fail(2, "unknown tool %q", tool)
	}
	var c contract
	data, err := os.ReadFile(filepath.Join(dir, "contract.json"))
	if err != nil {
		fail(2, "cannot read contract for %q: %v", tool, err)
	}
	if json.Unmarshal(data, &c) != nil {
		fail(2, "bad contract for %q", tool)
	}

	body, err := json.Marshal(map[string]any{
		"model": alias, "temperature": 0, "max_tokens": 400,
		"messages": []map[string]string{
			{"role": "system", "content": string(prompt)},
			{"role": "user", "content": "<input>" + text + "</input>"}, // untrusted data, as the prompt says
		},
	})
	if err != nil {
		fail(2, "cannot encode request: %v", err)
	}
	req, err := http.NewRequest("POST", strings.TrimRight(env("GATEWAY_URL", "http://localhost:4000"), "/")+"/v1/chat/completions", bytes.NewReader(body))
	if err != nil {
		fail(2, "bad GATEWAY_URL: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+env("GATEWAY_KEY", "sk-dev-only-master")) // in real use, the tool's own key
	res, err := (&http.Client{Timeout: 60 * time.Second}).Do(req)
	if err != nil {
		fail(2, "gateway call failed: %v", err)
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		fail(2, "gateway call failed: http %d", res.StatusCode)
	}
	var reply struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if json.NewDecoder(res.Body).Decode(&reply) != nil || len(reply.Choices) == 0 {
		fail(2, "gateway call failed: unreadable reply")
	}

	raw := reply.Choices[0].Message.Content
	ok := valid(raw, c)
	fmt.Printf("alias=%s valid=%v\n%s\n", alias, ok, raw)
	if !ok {
		os.Exit(1)
	}
}
