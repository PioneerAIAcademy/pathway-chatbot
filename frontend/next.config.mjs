/** @type {import('next').NextConfig} */
import fs from "fs";
import withLlamaIndex from "llamaindex/next";
import { withSentryConfig } from "@sentry/nextjs";
import webpack from "./webpack.config.mjs";

const nextConfig = JSON.parse(fs.readFileSync("./next.config.json", "utf-8"));
nextConfig.webpack = webpack;

// use withLlamaIndex to add necessary modifications for llamaindex library
export default withSentryConfig(withLlamaIndex(nextConfig), {
  // Suppress Sentry CLI output during builds
  silent: true,
  // Disable telemetry
  telemetry: false,
  // Don't upload source maps (requires SENTRY_AUTH_TOKEN — optional)
  sourcemaps: { disable: true },
});
