scp httperf_content measure_POST.py quilt@<NON_PROXY_IP>:~/
ssh quilt@<NON_PROXY_IP>

sudo apt-get install httperf
python3 measure_POST.py <PROXY_VM_IP>
