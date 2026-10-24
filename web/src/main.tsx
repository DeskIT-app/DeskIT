import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// The sheets first, so the cascade is the one Home was drawn with: B+,
// then the frame, then (through app.tsx) the kit and each place's own.
import "./bplus.css";     // the look he approved: the mockups' own stylesheet
import "./desk.css";      // the frame: the bar's life, the page, the sky, the toast
import App from "./app";

const root = document.getElementById("root");
if (root) createRoot(root).render(<StrictMode><App /></StrictMode>);
