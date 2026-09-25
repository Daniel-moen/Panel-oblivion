# ONE worker, several threads — deliberately.
#
# A crawl runs as a separate OS process (crawler.py): the web process pipes
# its stdout into the job log and polls DATA_DIR/crawl_progress.json into an
# in-memory dict (webapp.job), and Stop is forwarded to it as SIGTERM. That
# dict, the single-job guard and the stop flag live in this one worker; a
# second gunicorn worker would be a separate process with its own copy, so the
# dashboard would poll one process while the job ran under another and
# progress would appear frozen. Scale by threads, never by workers.
#
# The timeout is generous because a crawl holds a request only briefly, but
# Property24's backoffs can make a foreground call slow.
web: gunicorn webapp:app --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:$PORT
