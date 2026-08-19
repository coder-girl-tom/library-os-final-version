import { Container, getContainer } from '@cloudflare/containers';

// This Worker does nothing to your app — it's the thin gateway Cloudflare
// Containers requires to route incoming requests to your Docker container.
// Your Flask app, templates, static files, and app.py are untouched.
export class LibraryContainer extends Container {
  defaultPort = 8000; // matches `EXPOSE 8000` / gunicorn bind in your Dockerfile
  sleepAfter = '10m';  // spins the container down after 10 min idle; scales back up on next request
}

export default {
  async fetch(request, env) {
    // Single shared instance is fine at this traffic volume (one school,
    // <=500 requests/day). getContainer() with no id routes every request
    // to the same always-reused instance.
    const container = getContainer(env.LIBRARY_CONTAINER);
    return container.fetch(request);
  },
};
