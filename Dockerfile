FROM docker.paylocity.com/amazonlinux:2

# Install necessary packages
RUN yum update -y && \
    yum install -y tar gzip curl git unzip python3 python3-pip python3-setuptools python3-wheel cron

# Set Python 3 as the default python
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3 1 \
    && update-alternatives --set python /usr/bin/python3
RUN update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1
RUN pip3 install --upgrade pip requests setuptools pipenv
RUN pip3 install pykube
RUN pip3 install python-crontab
RUN pip3 install croniter

# Install kubectl
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && \
    install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# Adding file
ADD schedule /app/schedule
ADD test.py /app/test.py
RUN chmod a+x /app/test.py
ADD scheduler_classes.py /app/scheduler_classes.py
ENV ENVIRONMENT='prf'

# Verify installations
RUN kubectl version --client && \
    python --version && \
    pip3 --version

# Set the entrypoint
ENTRYPOINT ["/bin/bash"]