import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./app";
import "./bplus.css";     // the look he approved: the mockups' own stylesheet
import "./styles.css";    // what a live window needs on top of a picture

const root = document.getElementById("root");
if (root) createRoot(root).render(<StrictMode><App /></StrictMode>);
