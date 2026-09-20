import { FormEvent, useState } from "react";

import TopPlayList, {
  isTopPlaysResponse,
  TopPlaysResponse,
} from "./TopPlayList";

async function getErrorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null) {
      const detail = (body as Record<string, unknown>).detail;
      if (typeof detail === "string") {
        return detail;
      }
    }
  } catch {
    // Use the status-based fallback when the response is not JSON.
  }

  if (response.status === 404) {
    return "That osu! user was not found.";
  }
  if (response.status >= 400 && response.status < 500) {
    return "The search request was not valid.";
  }
  return "The backend could not complete the search.";
}

function App() {
  const [username, setUsername] = useState("");
  const [result, setResult] = useState<TopPlaysResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (isLoading) {
      return;
    }

    const submittedUsername = username.trim();
    setResult(null);
    setErrorMessage(null);

    if (!submittedUsername) {
      setErrorMessage("Enter an osu! username.");
      return;
    }

    setIsLoading(true);
    try {
      const response = await fetch(
        `/api/users/${encodeURIComponent(submittedUsername)}/top-plays`,
      );
      if (!response.ok) {
        throw new Error(await getErrorMessage(response));
      }

      const body: unknown = await response.json();
      if (!isTopPlaysResponse(body)) {
        throw new Error("The backend returned an unexpected response.");
      }

      setResult(body);
    } catch (error) {
      setErrorMessage(
        error instanceof TypeError
          ? "The backend is unavailable. Try again after it is running."
          : error instanceof Error
            ? error.message
            : "The search failed unexpectedly.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main>
      <h1>osumapscout</h1>
      <p>An osu!standard map recommendation project.</p>

      <form onSubmit={handleSubmit}>
        <label htmlFor="username">osu! username</label>
        <div className="search-controls">
          <input
            id="username"
            name="username"
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            disabled={isLoading}
            autoComplete="off"
          />
          <button type="submit" disabled={isLoading}>
            {isLoading ? "Searching..." : "Search"}
          </button>
        </div>
      </form>

      <div className="search-status" aria-live="polite">
        {isLoading && <p>Loading...</p>}
        {result && (
          <>
            <p>
              Found {result.count} top plays for {result.username}.
            </p>
            <TopPlayList result={result} />
          </>
        )}
        {errorMessage && <p className="error-message">{errorMessage}</p>}
      </div>
    </main>
  );
}

export default App;
