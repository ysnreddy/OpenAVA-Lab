do cd processing_pipeline 

# clone the cvat

git clone https://github.com/cvat-ai/cvat

cd cvat

# start the docker 

docker-compose up -d

# create admin account

docker exec -it cvat_server /bin/bash

From inside the container's shell, run the following command and follow the prompts to set a username, email, and password.

python3 manage.py createsuperuser

Access the CVAT Interface
Your local CVAT instance is now ready. Open your web browser and go to the following address to access it:

http://localhost:8080


## To run this with complete Database setup


*docker-compose -f docker-compose.yml -f docker-compose.override.yml up -d*
