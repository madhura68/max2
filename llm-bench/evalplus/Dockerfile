# EvalPlus 0.3.1 with HumanEval+ and MBPP+ baked in, so evaluation can run with --network none.
FROM python:3.12-slim
RUN pip install --no-cache-dir evalplus==0.3.1
# Cache readable/writable for the non-root uid the runs use (groundtruth is cached at evaluate time).
ENV XDG_CACHE_HOME=/opt/cache
RUN python -c "from evalplus.data import get_human_eval_plus, get_mbpp_plus; print(len(get_human_eval_plus()), len(get_mbpp_plus()))" \
 && chmod -R a+rwX /opt/cache
COPY gen.py alias_fix.py /opt/
WORKDIR /work
