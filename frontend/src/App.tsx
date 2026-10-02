import { FormEvent, useEffect, useState } from "react";

import PlayerAnalysis, { isPlayerAnalysisResponse, PlayerAnalysisResponse } from "./PlayerAnalysis";
import RecommendationList, { isRecommendationsResponse, RecommendationsResponse } from "./RecommendationList";
import TopPlayList, { isTopPlaysResponse, TopPlaysResponse } from "./TopPlayList";

const loadingMessages = [
  "Finding similar players...",
  "Checking their top plays...",
  "Comparing map attributes...",
  "Ranking recommendations...",
] as const;

function App() {
  const [username, setUsername] = useState("");
  const [topPlayCount, setTopPlayCount] = useState(10);
  const [isTopPlaysOpen, setIsTopPlaysOpen] = useState(false);
  const [topPlaysResult, setTopPlaysResult] = useState<TopPlaysResponse | null>(null);
  const [topPlaysError, setTopPlaysError] = useState<string | null>(null);
  const [isTopPlaysLoading, setIsTopPlaysLoading] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<PlayerAnalysisResponse | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [isAnalysisLoading, setIsAnalysisLoading] = useState(false);
  const [recommendationsResult, setRecommendationsResult] = useState<RecommendationsResponse | null>(null);
  const [recommendationsError, setRecommendationsError] = useState<string | null>(null);
  const [isRecommendationsLoading, setIsRecommendationsLoading] = useState(false);
  const [loadingMessageIndex, setLoadingMessageIndex] = useState(0);
  const isAnyRequestLoading = isTopPlaysLoading || isAnalysisLoading || isRecommendationsLoading;

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

  async function requestTopPlays() {
    if (isAnyRequestLoading) return;
    const submittedUsername = username.trim();
    setTopPlaysResult(null);
    setTopPlaysError(null);
    if (!submittedUsername) {
      setTopPlaysError("Enter an osu! username.");
      return;
    }
    setIsTopPlaysLoading(true);
    try {
      const response = await fetch(`/api/users/${encodeURIComponent(submittedUsername)}/top-plays?limit=${topPlayCount}`);
      if (!response.ok) throw new Error("The backend could not load top plays.");
      const body: unknown = await response.json();
      if (!isTopPlaysResponse(body)) throw new Error("The backend returned an unexpected response.");
      setTopPlaysResult(body);
    } catch (error) {
      setTopPlaysError(error instanceof TypeError
        ? "The backend is unavailable. Try again after it is running."
        : error instanceof Error ? error.message : "The top-play request failed unexpectedly.");
    } finally {
      setIsTopPlaysLoading(false);
    }
  }

  async function requestAnalysis() {
    if (isAnyRequestLoading) return;
    const submittedUsername = username.trim();
    setAnalysisResult(null);
    setAnalysisError(null);
    if (!submittedUsername) {
      setAnalysisError("Enter an osu! username.");
      return;
    }
    setIsAnalysisLoading(true);
    try {
      const response = await fetch(`/api/users/${encodeURIComponent(submittedUsername)}/analysis`);
      if (response.status === 404) throw new Error("No playstyle analysis is available for this user yet.");
      if (!response.ok) throw new Error("The backend could not load playstyle analysis.");
      const body: unknown = await response.json();
      if (!isPlayerAnalysisResponse(body)) throw new Error("The backend returned an unexpected analysis response.");
      setAnalysisResult(body);
    } catch (error) {
      setAnalysisError(error instanceof TypeError
        ? "The backend is unavailable. Try again after it is running."
        : error instanceof Error ? error.message : "The analysis request failed unexpectedly.");
    } finally {
      setIsAnalysisLoading(false);
    }
  }

  async function requestRecommendations(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isAnyRequestLoading) return;
    const submittedUsername = username.trim();
    setRecommendationsResult(null);
    setRecommendationsError(null);
    if (!submittedUsername) {
      setRecommendationsError("Enter an osu! username.");
      return;
    }
    setIsRecommendationsLoading(true);
    try {
      const response = await fetch(`/api/recommendations/${encodeURIComponent(submittedUsername)}?limit=20`);
      if (!response.ok) {
        if (response.status === 404) throw new Error("Couldn't find that osu! user.");
        if (response.status === 422) throw new Error("There isn't enough play data to generate recommendations for this user yet.");
        if (response.status === 502 || response.status === 503) throw new Error("osu! is temporarily unavailable. Try again in a bit.");
        throw new Error("Something went wrong while generating recommendations.");
      }
      const body: unknown = await response.json();
      if (!isRecommendationsResponse(body)) throw new Error("The backend returned an unexpected recommendation response.");
      setRecommendationsResult(body);
    } catch (error) {
      setRecommendationsError(error instanceof TypeError
        ? "The backend is unavailable. Try again after it is running."
        : error instanceof Error ? error.message : "Something went wrong while generating recommendations.");
    } finally {
      setIsRecommendationsLoading(false);
    }
  }

  return (
    <main>
      <h1>osumapscout</h1>
      <p>Find osu!standard maps that fit the way you play.</p>

      <form onSubmit={requestRecommendations}>
        <label htmlFor="username">osu! username</label>
        <div className="search-controls">
          <input id="username" name="username" type="text" value={username}
            onChange={(event) => setUsername(event.target.value)} disabled={isAnyRequestLoading} autoComplete="off" />
          <button className="recommendation-button" type="submit" disabled={isAnyRequestLoading}>
            {isRecommendationsLoading ? "Finding maps..." : "Get recommendations"}
          </button>
        </div>
      </form>

      <section className="player-section top-plays-section">
        <button className="section-toggle" type="button" aria-expanded={isTopPlaysOpen}
          aria-controls="top-plays-panel" onClick={() => setIsTopPlaysOpen((open) => !open)}>
          <span>Top Plays</span><span aria-hidden="true">{isTopPlaysOpen ? "▾" : "▸"}</span>
        </button>
        {isTopPlaysOpen && (
          <div id="top-plays-panel" className="section-panel">
            <div className="section-actions">
              <label htmlFor="top-play-count">Display count</label>
              <select id="top-play-count" value={topPlayCount}
                onChange={(event) => setTopPlayCount(Number(event.target.value))} disabled={isAnyRequestLoading}>
                {[10, 25, 50, 100].map((count) => <option key={count}>{count}</option>)}
              </select>
              <button type="button" className="secondary-button" disabled={isAnyRequestLoading}
                onClick={() => void requestTopPlays()}>
                {isTopPlaysLoading ? "Loading..." : "Load top plays"}
              </button>
            </div>
            <div aria-live="polite">
              {topPlaysResult && <TopPlayList result={topPlaysResult} />}
              {topPlaysError && <p className="error-message">{topPlaysError}</p>}
            </div>
          </div>
        )}
      </section>

      <section className="player-section analysis-section" aria-labelledby="playstyle-heading">
        <div className="section-heading-row">
          <h2 id="playstyle-heading">Playstyle Analysis</h2>
          <button type="button" className="secondary-button" disabled={isAnyRequestLoading}
            onClick={() => void requestAnalysis()}>
            {isAnalysisLoading ? "Loading..." : "View analysis"}
          </button>
        </div>
        <div aria-live="polite">
          {analysisResult && <PlayerAnalysis analysis={analysisResult} />}
          {analysisError && <p className="error-message">{analysisError}</p>}
        </div>
      </section>

      <section className="player-section recommendation-section" aria-labelledby="map-recommendations-heading">
        <h2 id="map-recommendations-heading">Map Recommendations</h2>
        <div className="recommendations-status" aria-live="polite" aria-busy={isRecommendationsLoading}>
          {isRecommendationsLoading && (
            <div className="recommendation-loader" role="status">
              <span className="loading-orbit" aria-hidden="true"><span /></span>
              <p>{loadingMessages[loadingMessageIndex]}</p>
            </div>
          )}
          {recommendationsResult && <RecommendationList result={recommendationsResult} />}
          {recommendationsError && <p className="error-message">{recommendationsError}</p>}
        </div>
      </section>
    </main>
  );
}

export default App;
