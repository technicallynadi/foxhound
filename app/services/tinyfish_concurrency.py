"""Global TinyFish concurrency limit.

Single process-wide semaphore shared by all features:
dossier, recon, interview prep, discovery, network map, watchdog.

Controls how many TinyFish browser sessions run simultaneously.
Each session is independent — they don't share browsers.
The semaphore just prevents overloading the server (1 shared CPU, 1GB RAM).

Bump this number if you upgrade the Fly.io machine.
"""

import asyncio

TINYFISH_SEMAPHORE = asyncio.Semaphore(3)
