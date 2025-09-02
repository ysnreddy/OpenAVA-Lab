# AVA Dataset Management System - Deployment Plan

## Overview

This deployment plan transforms your collection of individual scripts into a unified, production-ready web application using FastAPI and Streamlit, containerized with Docker and ready for AWS deployment.

## Target Architecture

```
+---------------------------+
|      Web Browser          |
|  (Admin accesses one URL) |
+---------------------------+
              |
              | HTTP Requests
              ▼
+---------------------------+
|    FastAPI Web Server     |
| (main.py)                 |
|---------------------------|
| - Serves a root page with |
|   links to dashboards     |
| - Manages configuration   |
| - Handles API logic       |
+---------------------------+
       |               |
       | Serves Page   | Serves Page
       ▼               ▼
+----------------+   +----------------+
| Streamlit App 1|   | Streamlit App 2|
| (Task Creation)|   | (QC Dashboard) |
+----------------+   +----------------+
```

## Phase 1: Project Refactoring

### 1.1 Directory Structure Setup

Create the following professional project structure:

```
your_project_name/
├── app/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py           # Configuration management
│   ├── pages/
│   │   ├── __init__.py
│   │   ├── 01_Task_Creation.py # Renamed from app.py
│   │   └── 02_Quality_Control.py # Renamed from admin_app.py
│   └── services/
│       ├── __init__.py
│       ├── assignment_generator.py
│       ├── cvat_integration.py
│       ├── dataset_generator.py
│       ├── post_annotation_service.py
│       └── quality_service.py
├── config/
│   └── attributes.json         # External config for action attributes
├── data/
│   └── (Your data folders: uploads, cvat_xmls, etc.)
├── tools/
│   └── proposals_to_cvat.py
├── .env                        # Environment variables and secrets
├── .env.example                # Template for environment variables
├── main.py                     # FastAPI application entry point
├── requirements.txt
└── Dockerfile
```

**Action Items:**
- [ ] Create new directory structure
- [ ] Move existing scripts to appropriate locations
- [ ] Rename `app.py` to `01_Task_Creation.py`
- [ ] Rename `admin_app.py` to `02_Quality_Control.py`
- [ ] Create all `__init__.py` files for Python packages

### 1.2 Configuration Management Implementation

#### A. Environment Variables Setup

Create `.env` file in project root:

```ini
# .env
CVAT_HOST="http://localhost:8080"
CVAT_USERNAME="your_admin_user"
CVAT_PASSWORD="your_admin_password"

DB_NAME="cvat_annotations"
DB_USER="postgres"
DB_PASSWORD="mysecretpassword"
DB_HOST="localhost"
DB_PORT="5432"
```

Create `.env.example` template:

```ini
# .env.example
CVAT_HOST="http://localhost:8080"
CVAT_USERNAME="your_admin_user"
CVAT_PASSWORD="your_admin_password"

DB_NAME="cvat_annotations"
DB_USER="postgres"
DB_PASSWORD="your_database_password"
DB_HOST="localhost"
DB_PORT="5432"
```

**Action Items:**
- [ ] Create `.env` file with actual credentials
- [ ] Create `.env.example` template
- [ ] Add `.env` to `.gitignore`
- [ ] Install `python-dotenv`: `pip install python-dotenv`

#### B. External Configuration Files

Create `config/attributes.json`:

```json
{
    "walking_behavior": {"options": ["unknown", "normal_walk", "..."]},
    "phone_usage": {"options": ["unknown", "no_phone", "..."]},
    "additional_attributes": {"options": ["..."]}
}
```

**Action Items:**
- [ ] Move `ATTRIBUTE_DEFINITIONS` from Python code to JSON
- [ ] Create `config/attributes.json`
- [ ] Validate JSON structure

#### C. Configuration Module

Create `app/core/config.py`:

```python
import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

class Settings:
    # CVAT Credentials
    CVAT_HOST: str = os.getenv("CVAT_HOST")
    CVAT_USERNAME: str = os.getenv("CVAT_USERNAME")
    CVAT_PASSWORD: str = os.getenv("CVAT_PASSWORD")

    # Database Credentials
    DB_PARAMS: dict = {
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "host": os.getenv("DB_HOST"),
        "port": os.getenv("DB_PORT")
    }

    # Load Attribute Definitions
    ATTRIBUTE_DEFINITIONS: dict = {}
    attr_path = Path('config/attributes.json')
    if attr_path.exists():
        with open(attr_path, 'r') as f:
            ATTRIBUTE_DEFINITIONS = json.load(f)

# Create a single settings object to be imported by other modules
settings = Settings()
```

**Action Items:**
- [ ] Create configuration module
- [ ] Test configuration loading
- [ ] Update all scripts to use settings object

## Phase 2: FastAPI + Streamlit Integration

### 2.1 Main FastAPI Application

Create `main.py`:

```python
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import subprocess
import threading
import time

app = FastAPI(title="AVA Dataset Management System")

# Store subprocesses to manage them
streamlit_processes = {}

def run_streamlit_app(path: str, port: int):
    """Function to run a Streamlit app as a subprocess."""
    subprocess.run(["streamlit", "run", path, "--server.port", str(port), "--server.headless", "true"])

@app.on_event("startup")
async def startup_event():
    """Start the Streamlit apps on different ports when FastAPI starts."""
    task_creation_port = 8501
    qc_dashboard_port = 8502
    
    task_thread = threading.Thread(target=run_streamlit_app, args=(f"app/pages/01_Task_Creation.py", task_creation_port), daemon=True)
    qc_thread = threading.Thread(target=run_streamlit_app, args=(f"app/pages/02_Quality_Control.py", qc_dashboard_port), daemon=True)
    
    task_thread.start()
    time.sleep(2) # Give it a moment to start
    qc_thread.start()

@app.get("/", response_class=HTMLResponse)
async def root():
    """Main landing page with links to the dashboards."""
    return """
    <html>
        <head><title>AVA Dataset Dashboard</title></head>
        <body>
            <h1>AVA Dataset Management System</h1>
            <ul>
                <li><a href="http://localhost:8501" target="_blank">Task Creation Dashboard</a></li>
                <li><a href="http://localhost:8502" target="_blank">Quality Control Dashboard</a></li>
            </ul>
        </body>
    </html>
    """
```

**Action Items:**
- [ ] Create main FastAPI application
- [ ] Test local FastAPI server startup
- [ ] Verify Streamlit apps launch correctly

### 2.2 Streamlit Apps Adaptation

Update imports in both Streamlit applications:

```python
# In 01_Task_Creation.py and 02_Quality_Control.py
from app.core.config import settings
from app.services.cvat_integration import CVATClient

# Replace hardcoded credentials with:
client = CVATClient(
    host=settings.CVAT_HOST, 
    username=settings.CVAT_USERNAME, 
    password=settings.CVAT_PASSWORD
)

# Replace database parameters with:
pool = init_connection_pool(settings.DB_PARAMS)
```

**Action Items:**
- [ ] Update imports in all Streamlit apps
- [ ] Replace hardcoded credentials with settings
- [ ] Test both Streamlit apps individually
- [ ] Test integration with FastAPI server

## Phase 3: Containerization

### 3.1 Dockerfile Creation

Create `Dockerfile` in project root:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Copy and install requirements first to leverage Docker layer caching
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port FastAPI will run on
EXPOSE 8000

# Command to run the FastAPI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Action Items:**
- [ ] Create Dockerfile
- [ ] Update `requirements.txt` with all dependencies
- [ ] Test Docker image build locally
- [ ] Test container startup

### 3.2 Docker Compose Integration

Add to your existing `docker-compose.yml`:

```yaml
services:
  # ... your existing cvat and postgres services ...

  ava_dashboard:
    build:
      context: ./your_project_name # Path to your app's Dockerfile
    container_name: ava_dashboard
    restart: always
    ports:
      - "8000:8000" # FastAPI
      - "8501:8501" # Streamlit Task Creation
      - "8502:8502" # Streamlit QC
    volumes:
      - ./your_project_name/data:/app/data # Mount data directory
    environment:
      - CVAT_HOST=http://cvat_server:8080
      - DB_HOST=cvat_db
    networks:
      - cvat # Connect to the same network as CVAT and the DB
    depends_on:
      - cvat_server
      - cvat_db
```

**Action Items:**
- [ ] Update docker-compose.yml
- [ ] Test full stack deployment locally
- [ ] Verify network connectivity between services
- [ ] Test data persistence with volumes

## Phase 4: Local Testing and Validation

### 4.1 Testing Checklist

**Environment Setup:**
- [ ] All environment variables load correctly
- [ ] Configuration files parse without errors
- [ ] Database connections work
- [ ] CVAT API connections work

**Application Functionality:**
- [ ] FastAPI server starts and serves landing page
- [ ] Both Streamlit apps launch correctly
- [ ] Task creation workflow works end-to-end
- [ ] Quality control dashboard displays data
- [ ] File uploads and processing work

**Containerization:**
- [ ] Docker image builds successfully
- [ ] Container starts without errors
- [ ] All ports are accessible
- [ ] Volume mounts work correctly
- [ ] Network connectivity between containers

### 4.2 Performance Testing

- [ ] Load testing with multiple concurrent users
- [ ] Memory usage monitoring
- [ ] Response time measurements
- [ ] File processing performance validation

## Phase 5: AWS Deployment Strategy

### 5.1 AWS Services Overview

**Core Services:**
- **ECR (Elastic Container Registry):** Private Docker image repository
- **ECS (Elastic Container Service):** Container orchestration
- **RDS (Relational Database Service):** Managed PostgreSQL database
- **ALB (Application Load Balancer):** Traffic routing and SSL termination
- **VPC (Virtual Private Cloud):** Network isolation and security

### 5.2 Pre-Deployment Setup

**AWS Account Preparation:**
- [ ] AWS account setup and billing configuration
- [ ] IAM user creation with appropriate permissions
- [ ] AWS CLI installation and configuration
- [ ] ECR repository creation

**Infrastructure as Code:**
- [ ] Create CloudFormation or Terraform templates
- [ ] Define VPC, subnets, and security groups
- [ ] Configure RDS instance specifications
- [ ] Set up ECS cluster and task definitions

### 5.3 Database Migration

**RDS Setup:**
- [ ] Create RDS PostgreSQL instance
- [ ] Configure security groups for database access
- [ ] Set up automated backups and monitoring
- [ ] Migrate existing database schema and data

**Connection Configuration:**
- [ ] Update environment variables for RDS endpoint
- [ ] Test database connectivity from local environment
- [ ] Validate all database operations work with RDS

### 5.4 Container Deployment

**ECR Image Management:**
- [ ] Build production Docker image
- [ ] Tag image appropriately (version/environment)
- [ ] Push image to ECR repository
- [ ] Set up automated image builds (optional)

**ECS Configuration:**
- [ ] Create ECS cluster
- [ ] Define task definitions for each service
- [ ] Configure service discovery
- [ ] Set up auto-scaling policies
- [ ] Configure health checks

### 5.5 Load Balancer and SSL

**Application Load Balancer:**
- [ ] Create ALB with appropriate listeners
- [ ] Configure target groups for each service
- [ ] Set up health check endpoints
- [ ] Configure SSL certificate (ACM or third-party)

**Domain and DNS:**
- [ ] Configure Route 53 or external DNS
- [ ] Set up domain pointing to ALB
- [ ] Test SSL certificate installation
- [ ] Verify HTTPS redirects work correctly

### 5.6 Security Configuration

**Network Security:**
- [ ] Configure VPC with public/private subnets
- [ ] Set up NAT Gateway for private subnet internet access
- [ ] Configure security groups with minimal required access
- [ ] Enable VPC Flow Logs for monitoring

**Application Security:**
- [ ] Enable AWS WAF for web application protection
- [ ] Configure CloudTrail for API logging
- [ ] Set up AWS Secrets Manager for sensitive data
- [ ] Enable encryption at rest and in transit

### 5.7 Monitoring and Logging

**CloudWatch Setup:**
- [ ] Configure application and infrastructure metrics
- [ ] Set up log aggregation from containers
- [ ] Create dashboards for key metrics
- [ ] Configure alerting for critical issues

**Health Monitoring:**
- [ ] Implement application health check endpoints
- [ ] Set up uptime monitoring
- [ ] Configure automated recovery procedures
- [ ] Test disaster recovery scenarios

## Phase 6: Deployment Execution

### 6.1 Staging Environment

- [ ] Deploy to staging environment first
- [ ] Run full integration tests
- [ ] Performance testing under load
- [ ] Security scanning and penetration testing
- [ ] User acceptance testing

### 6.2 Production Deployment

**Blue-Green Deployment:**
- [ ] Set up blue-green deployment strategy
- [ ] Deploy to green environment
- [ ] Run smoke tests on green environment
- [ ] Switch traffic from blue to green
- [ ] Monitor for issues and rollback if needed

**Post-Deployment:**
- [ ] Verify all services are running correctly
- [ ] Test all application functionality
- [ ] Monitor logs and metrics
- [ ] Document any issues and resolutions

## Phase 7: Maintenance and Operations

### 7.1 Ongoing Maintenance

**Regular Tasks:**
- [ ] Monitor application performance and costs
- [ ] Apply security updates and patches
- [ ] Review and optimize resource usage
- [ ] Backup and disaster recovery testing
- [ ] Documentation updates

**Scaling Considerations:**
- [ ] Monitor usage patterns
- [ ] Adjust auto-scaling policies as needed
- [ ] Optimize database performance
- [ ] Consider CDN for static assets
- [ ] Plan for traffic growth

### 7.2 CI/CD Pipeline (Future Enhancement)

**Automated Deployment:**
- [ ] Set up GitHub Actions or AWS CodePipeline
- [ ] Implement automated testing
- [ ] Configure staging and production deployments
- [ ] Set up rollback procedures
- [ ] Implement feature flags for safe deployments

## Success Criteria

**Technical Success:**
- [ ] Application accessible via public URL
- [ ] All functionality working as expected
- [ ] Response times under acceptable thresholds
- [ ] High availability (99.9% uptime)
- [ ] Secure data handling and transmission

**Operational Success:**
- [ ] Monitoring and alerting in place
- [ ] Documented deployment and recovery procedures
- [ ] Cost optimization achieved
- [ ] Team trained on AWS operations
- [ ] Scalability roadmap established

## Risk Mitigation

**Common Risks:**
- **Data Loss:** Implement automated backups and test recovery procedures
- **Security Breaches:** Follow AWS security best practices and regular audits
- **Performance Issues:** Load testing and monitoring before go-live
- **Cost Overruns:** Set up billing alerts and resource optimization
- **Deployment Failures:** Blue-green deployment and rollback procedures

## Timeline Estimate

**Phase 1-2 (Refactoring):** 2-3 weeks
**Phase 3 (Containerization):** 1 week  
**Phase 4 (Local Testing):** 1 week
**Phase 5-6 (AWS Deployment):** 2-3 weeks
**Phase 7 (Documentation & Training):** 1 week

**Total Estimated Timeline:** 7-9 weeks

## Budget Considerations

**AWS Monthly Costs (Estimated):**
- ECS Fargate: $50-200/month (depending on usage)
- RDS PostgreSQL: $50-150/month (depending on instance size)
- ALB: $20-30/month
- Data Transfer: $10-50/month
- Other services (CloudWatch, ECR, etc.): $20-40/month

**Total Estimated Monthly Cost:** $150-470/month

*Note: Actual costs will vary based on usage patterns, data volume, and chosen instance sizes.*