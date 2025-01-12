FROM python:3.9-slim-buster

# Copy repository content to container
RUN mkdir /app
WORKDIR /CVRtoAstuto
COPY ["./CVR to Astuto/", "./"]

# Begin setup for Python
RUN pip install requests schedule

# Lauch Dream Packet
CMD python "CVR to Astuto.py"