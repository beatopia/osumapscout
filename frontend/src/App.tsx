import { FormEvent, useEffect, useRef, useState } from "react";

import PlayerAnalysis, { isPlayerAnalysisResponse, PlayerAnalysisResponse } from "./PlayerAnalysis";
import RecommendationList, { isRecommendationsResponse, RecommendationsResponse } from "./RecommendationList";

const loadingMessages = ["Finding similar players...", "Checking their top plays...", "Comparing map attributes...", "Ranking recommendations..."] as const;

function App() {
  const [username, setUsername] = useState("");
  const [searchedUsername, setSearchedUsername] = useState<string | null>(null);
  const [analysisResult, setAnalysisResult] = useState<PlayerAnalysisResponse | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [isAnalysisLoading, setIsAnalysisLoading] = useState(false);
  const [recommendationsResult, setRecommendationsResult] = useState<RecommendationsResponse | null>(null);
  const [recommendationsError, setRecommendationsError] = useState<string | null>(null);
  const [isRecommendationsLoading, setIsRecommendationsLoading] = useState(false);
  const [playerError, setPlayerError] = useState<string | null>(null);
  const [loadingMessageIndex, setLoadingMessageIndex] = useState(0);
  const requestSequence = useRef(0);
  const activeController = useRef<AbortController | null>(null);
  const isPlayerLoading = isAnalysisLoading || isRecommendationsLoading;

  useEffect(() => {
    if (!isRecommendationsLoading) {
      setLoadingMessageIndex(0);
      return;
    }
    const timer = window.setInterval(() => {
      setLoadingMessageIndex((current) => Math.min(current + 1, loadingMessages.length - 1));
    }, 1800);
    return () => window.clearInterval(timer);
  }, [isRecommendationsLoading]);

  useEffect(() => () => activeController.current?.abort(), []);

  async function searchPlayer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submittedUsername = username.trim();
    if (!submittedUsername) {
      setPlayerError("Enter an osu! username.");
      return;
    }
    activeController.current?.abort();
    const controller = new AbortController();
    activeController.current = controller;
    const sequence = ++requestSequence.current;
    setSearchedUsername(submittedUsername);
    setPlayerError(null);
    setAnalysisResult(null);
    setAnalysisError(null);
    setRecommendationsResult(null);
    setRecommendationsError(null);
    setIsRecommendationsLoading(true);
    setIsAnalysisLoading(true);

    let playerWasNotFound = false;
    try {
      const response = await fetch(`/api/recommendations/${encodeURIComponent(submittedUsername)}?limit=20`, { signal: controller.signal });
      if (!response.ok) {
        if (response.status === 404) { playerWasNotFound = true; throw new Error("Couldn't find that osu! user."); }
        if (response.status === 422) throw new Error("There isn't enough play data to generate recommendations for this user yet.");
        if (response.status === 502 || response.status === 503) throw new Error("osu! is temporarily unavailable. Try again in a bit.");
        throw new Error("Something went wrong while generating recommendations.");
      }
      const body: unknown = await response.json();
      if (!isRecommendationsResponse(body)) throw new Error("The backend returned an unexpected recommendation response.");
      if (sequence === requestSequence.current) setRecommendationsResult(body);
    } catch (error) {
      if (sequence === requestSequence.current && !controller.signal.aborted) {
        const message = error instanceof TypeError ? "The backend is unavailable. Try again after it is running."
          : error instanceof Error ? error.message : "Something went wrong while generating recommendations.";
        if (playerWasNotFound) { setPlayerError(message); setSearchedUsername(null); }
        else setRecommendationsError(message);
      }
    } finally {
      if (sequence === requestSequence.current) setIsRecommendationsLoading(false);
    }

    if (playerWasNotFound || controller.signal.aborted) {
      if (sequence === requestSequence.current) setIsAnalysisLoading(false);
      return;
    }
    try {
      const response = await fetch(`/api/users/${encodeURIComponent(submittedUsername)}/analysis`, { signal: controller.signal });
      if (response.status === 404) throw new Error("No playstyle analysis is available for this user yet.");
      if (!response.ok) throw new Error("The backend could not load playstyle analysis.");
      const body: unknown = await response.json();
      if (!isPlayerAnalysisResponse(body)) throw new Error("The backend returned an unexpected analysis response.");
      if (sequence === requestSequence.current) setAnalysisResult(body);
    } catch (error) {
      if (sequence === requestSequence.current && !controller.signal.aborted) {
        setAnalysisError(error instanceof TypeError ? "The backend is unavailable. Try again after it is running."
          : error instanceof Error ? error.message : "The analysis request failed unexpectedly.");
      }
    } finally {
      if (sequence === requestSequence.current) setIsAnalysisLoading(false);
    }
  }

  const playerName = recommendationsResult?.target_username ?? analysisResult?.username ?? searchedUsername;
  return (
    <main>
      <h1>osumapscout</h1>
      <p>Find osu!standard maps that fit the way you play.</p>
      <form onSubmit={searchPlayer}>
        <label htmlFor="username">osu! username</label>
        <div className="search-controls">
          <input id="username" name="username" type="text" value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="off" />
          <button className="recommendation-button" type="submit" disabled={isPlayerLoading}>{isPlayerLoading ? "Searching..." : "Search"}</button>
        </div>
      </form>
      {playerError && <p className="error-message search-status">{playerError}</p>}
      {playerName && <div className="player-view">
        <section className="analysis-section" aria-label="Player Overview">
          <div aria-live="polite" aria-busy={isAnalysisLoading}>{isAnalysisLoading && <p>Loading player overview...</p>}{analysisResult && <PlayerAnalysis analysis={analysisResult} recommendationProfile={recommendationsResult?.target_profile ?? null} preferences={recommendationsResult?.preferences ?? null} />}{analysisError && <p className="error-message">{analysisError}</p>}</div>
        </section>
        <section className="player-section recommendation-section">
          <div className="recommendations-status" aria-live="polite" aria-busy={isRecommendationsLoading}>
            {isRecommendationsLoading && <div className="recommendation-loader" role="status"><span className="loading-orbit" aria-hidden="true"><span /></span><p>{loadingMessages[loadingMessageIndex]}</p></div>}
            {recommendationsResult && <RecommendationList key={recommendationsResult.target_user_id} result={recommendationsResult} />}
            {recommendationsError && <p className="error-message">{recommendationsError}</p>}
          </div>
        </section>
      </div>}
    </main>
  );
}

export default App;
