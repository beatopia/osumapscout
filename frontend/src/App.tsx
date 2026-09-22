import { FormEvent, useState } from "react";

import PlayerAnalysis, {
  isPlayerAnalysisResponse,
  PlayerAnalysisResponse,
} from "./PlayerAnalysis";
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
  const [topPlaysResult, setTopPlaysResult] =
    useState<TopPlaysResponse | null>(null);
  const [topPlaysError, setTopPlaysError] = useState<string | null>(null);
  const [isTopPlaysLoading, setIsTopPlaysLoading] = useState(false);
  const [analysisResult, setAnalysisResult] =
    useState<PlayerAnalysisResponse | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [isAnalysisLoading, setIsAnalysisLoading] = useState(false);
  const isAnyRequestLoading = isTopPlaysLoading || isAnalysisLoading;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (isAnyRequestLoading) {
      return;
    }

    const submittedUsername = username.trim();
    setTopPlaysResult(null);
    setTopPlaysError(null);

    if (!submittedUsername) {
      setTopPlaysError("Enter an osu! username.");
      return;
    }

    setIsTopPlaysLoading(true);
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

      setTopPlaysResult(body);
    } catch (error) {
      setTopPlaysError(
        error instanceof TypeError
          ? "The backend is unavailable. Try again after it is running."
          : error instanceof Error
            ? error.message
            : "The search failed unexpectedly.",
      );
    } finally {
      setIsTopPlaysLoading(false);
    }
  }

  async function handleAnalysisRequest() {
    if (isAnyRequestLoading) {
      return;
    }

    const submittedUsername = username.trim();
    setAnalysisResult(null);
    setAnalysisError(null);

    if (!submittedUsername) {
      setAnalysisError("Enter an osu! username.");
      return;
    }

    setIsAnalysisLoading(true);
    try {
      const response = await fetch(
        `/api/users/${encodeURIComponent(submittedUsername)}/analysis`,
      );
      if (response.status === 404) {
        throw new Error("No persisted analysis found for this user.");
      }
      if (!response.ok) {
        throw new Error("The backend could not load persisted analysis.");
      }

      const body: unknown = await response.json();
      if (!isPlayerAnalysisResponse(body)) {
        throw new Error("The backend returned an unexpected analysis response.");
      }

      setAnalysisResult(body);
    } catch (error) {
      setAnalysisError(
        error instanceof TypeError
          ? "The backend is unavailable. Try again after it is running."
          : error instanceof Error
            ? error.message
            : "The analysis request failed unexpectedly.",
      );
    } finally {
      setIsAnalysisLoading(false);
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
            disabled={isAnyRequestLoading}
            autoComplete="off"
          />
          <button type="submit" disabled={isAnyRequestLoading}>
            {isTopPlaysLoading ? "Searching..." : "Search live top plays"}
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={isAnyRequestLoading}
            onClick={handleAnalysisRequest}
          >
            {isAnalysisLoading ? "Loading analysis..." : "View persisted analysis"}
          </button>
        </div>
      </form>

      <div className="search-status" aria-live="polite">
        {isTopPlaysLoading && <p>Loading live top plays...</p>}
        {topPlaysResult && (
          <>
            <p>
              Found {topPlaysResult.count} top plays for {topPlaysResult.username}.
            </p>
            <TopPlayList result={topPlaysResult} />
          </>
        )}
        {topPlaysError && <p className="error-message">{topPlaysError}</p>}
      </div>

      <div className="analysis-status" aria-live="polite">
        {isAnalysisLoading && <p>Loading persisted analysis...</p>}
        {analysisResult && <PlayerAnalysis analysis={analysisResult} />}
        {analysisError && <p className="error-message">{analysisError}</p>}
      </div>
    </main>
  );
}

export default App;
