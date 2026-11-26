import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import "./style.css";

const query = new QueryClient();
const root = document.getElementById("root");
if (!root) throw new Error("root missing");
createRoot(root).render(
  <React.StrictMode>
    <QueryClientProvider client={query}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
