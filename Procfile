# ONE worker, several threads — deliberately.
#
# Crawl/score jobs run in background threads inside the web process and report
# progress through an in-memory dict (webapp.job). A second gunicorn worker
# would be a separate process with its own copy of that dict, so the dashboard
# would poll one process while the job ran in another and progress would appear
# frozen. Scale by threads, never by workers.
#
# The timeout is generous because a crawl holds a request only briefly, but
# Property24's backoffs can make a foreground call slow.
web: gunicorn webapp:app --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:$PORT
