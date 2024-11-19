FROM docker.paylocity.com/amazonlinux:2023.6.20241031.0

WORKDIR /app

# Install necessary packages
RUN yum update -y && \
    yum install --allowerasing -y tar gzip curl git unzip python3 python3-pip python3-setuptools python3-wheel

# Copy over requirements.txt
COPY requirements.txt .

# Set Python 3 as the default python
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3 1 \
    && update-alternatives --set python /usr/bin/python3
RUN update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install awscli v2
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && \
    unzip awscliv2.zip && \
    ./aws/install

# Install kubectl
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && \
    install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# Adding file
ADD schedule /app/schedule
ADD watch_test.py /app/watch_test.py
RUN chmod a+x /app/watch_test.py
ADD crd_test.py /app/crd_test.py
RUN chmod a+x /app/crd_test.py
ADD scheduler_classes.py /app/scheduler_classes.py
ENV ENVIRONMENT='dev'

# Verify installations
RUN kubectl version --client && \
    python --version && \
    pip3 --version

# Set the entrypoint
ENTRYPOINT ["/bin/bash"]