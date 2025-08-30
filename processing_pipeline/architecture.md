# Architecture Documentation
## Multi-Annotator CVAT Pipeline for AVA-Style Datasets

### Table of Contents
1. [System Overview](#system-overview)
2. [Core Components](#core-components)
3. [Data Flow Architecture](#data-flow-architecture)
4. [Service Layer](#service-layer)
5. [Database Schema](#database-schema)
6. [Integration Points](#integration-points)
7. [Security Considerations](#security-considerations)
8. [Scalability Design](#scalability-design)

---

## System Overview

The Multi-Annotator CVAT Pipeline is a distributed system designed to handle large-scale video annotation workflows for action recognition datasets. The architecture follows a microservices pattern with event-driven communication, ensuring scalability and maintainability.

### Design Principles
- **Event-Driven Architecture**: Webhooks trigger automated workflows
- **Separation of Concerns**: Clear boundaries between task creation, annotation, and quality control
- **Data Persistence**: All annotations stored in structured database for audit trails
- **Horizontal Scalability**: Support for multiple annotators and concurrent tasks
- **Quality Assurance**: Built-in Inter-Annotator Agreement calculations

### Technology Stack
- **Frontend**: Streamlit (Task Dashboard, Admin Panel)
- **Backend**: Python (Flask webhooks, processing services)
- **Database**: PostgreSQL (annotation storage, project management)
- **Containerization**: Docker + Docker Compose
- **Annotation Platform**: CVAT (Computer Vision Annotation Tool)
- **Computer Vision**: OpenCV, YOLOX, DeepSORT

---

## Core Components

### 1. Task Creation Subsystem
**Purpose**: Converts video data into annotatable tasks in CVAT

**Components**:
- **Pre-annotation Generator** (`proposals_to_cvat.py`)
- **Task Dashboard** (Streamlit UI)
- **CVAT Integration Service** (`cvat_integration.py`)

**Responsibilities**:
- Process video clips into frames
- Generate object detection proposals
- Create CVAT projects and tasks
- Assign tasks to annotators with overlap configuration

### 2. Annotation Management Subsystem
**Purpose**: Handles the annotation workflow and task assignments

**Components**:
- **CVAT Instance** (Dockerized)
- **Webhook Listener** (`webhook_listener.py`)
- **Assignment Logic** (Built into task creation)

**Responsibilities**:
- Provide annotation interface for users
- Track task completion status
- Trigger post-annotation workflows

### 3. Post-Annotation Processing Subsystem
**Purpose**: Retrieves and processes completed annotations

**Components**:
- **Post-Annotation Service** (`post_annotation_service.py`)
- **Data Retrieval Module**
- **Database Storage Layer**

**Responsibilities**:
- Automatically retrieve completed annotations from CVAT
- Parse and normalize annotation data
- Store structured data in PostgreSQL

### 4. Quality Control Subsystem
**Purpose**: Implements quality assurance measures

**Components**:
- **Admin Dashboard** (Streamlit UI)
- **Quality Service** (`quality_service.py`)
- **Consensus Algorithm**

**Responsibilities**:
- Calculate Inter-Annotator Agreement (IoU)
- Compute Cohen's Kappa for action attributes
- Apply consensus logic for final dataset generation

---

## Data Flow Architecture

### Phase 1: Task Creation Flow
```
[Video Clips] → [Frame Extraction] → [Object Detection (YOLOX + DeepSORT)]
                                                ↓
[Pre-annotations (XML)] ← [proposals_to_cvat.py] ← [Dense Proposals]
                                                ↓
[CVAT Tasks] ← [cvat_integration.py] ← [Task Dashboard UI]
```

### Phase 2: Annotation Flow
```
[Annotator Interface (CVAT)] → [Job Completion] → [Status Change]
                                                        ↓
[Webhook Trigger] → [webhook_listener.py] → [post_annotation_service.py]
                                                        ↓
[PostgreSQL Database] ← [Structured Annotations]
```

### Phase 3: Quality Control Flow
```
[Admin Dashboard] → [Quality Analysis] → [IoU + Kappa Calculation]
                                                        ↓
[Consensus Logic] → [Final Dataset Generation] → [train.csv]
```

---

## Service Layer

### 1. Web Services

#### Task Creation Service
- **Endpoint**: Streamlit Dashboard (`app.py`)
- **Functionality**: Project management, task configuration, batch uploads
- **Dependencies**: CVAT API, File System

#### Admin Service
- **Endpoint**: Streamlit Dashboard (`admin_app.py`)
- **Functionality**: Quality control, dataset generation, project monitoring
- **Dependencies**: PostgreSQL, Quality Service

#### Webhook Service
- **Endpoint**: Flask Server (`webhook_listener.py`)
- **Port**: 5000 (configurable)
- **Functionality**: Receives CVAT status notifications
- **Dependencies**: Post-Annotation Service

### 2. Background Services

#### Post-Annotation Service
- **Type**: Event-driven processor
- **Trigger**: Webhook notifications
- **Functionality**: Annotation retrieval and storage
- **Dependencies**: CVAT API, PostgreSQL

#### Quality Service
- **Type**: Analysis engine
- **Functionality**: Statistical calculations, consensus algorithms
- **Dependencies**: PostgreSQL, NumPy/SciPy

---

## Database Schema

### Projects Table
```sql
CREATE TABLE projects (
    project_id INTEGER PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    organization_slug VARCHAR(255),
    total_tasks INTEGER,
    completed_tasks INTEGER DEFAULT 0
);
```

### Tasks Table
```sql
CREATE TABLE tasks (
    task_id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(project_id),
    name VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'annotation',
    assignee VARCHAR(255),
    video_clip VARCHAR(255),
    retrieved_at TIMESTAMP WITH TIME ZONE,
    qc_status VARCHAR(50) DEFAULT 'pending',
    overlap_group INTEGER
);
```

### Annotations Table
```sql
CREATE TABLE annotations (
    annotation_id SERIAL PRIMARY KEY,
    task_id INTEGER REFERENCES tasks(task_id),
    track_id INTEGER NOT NULL,
    frame INTEGER NOT NULL,
    xtl REAL NOT NULL,
    ytl REAL NOT NULL,
    xbr REAL NOT NULL,
    ybr REAL NOT NULL,
    outside BOOLEAN DEFAULT FALSE,
    attributes JSONB,
    annotator VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### Quality Metrics Table
```sql
CREATE TABLE quality_metrics (
    metric_id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(project_id),
    task_group INTEGER,
    metric_type VARCHAR(50), -- 'iou', 'kappa'
    metric_value REAL,
    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    details JSONB
);
```

---

## Integration Points

### 1. CVAT API Integration
**Authentication**: Token-based authentication
**Endpoints Used**:
- `/api/projects` - Project management
- `/api/tasks` - Task creation and management
- `/api/jobs` - Job assignment and status
- `/api/tasks/{id}/annotations` - Annotation retrieval

**Configuration Requirements**:
```yaml
# docker-compose.override.yml
services:
  cvat_server:
    environment:
      SMOKESCREEN_OPTS: --unsafe-allow-private-ranges
  cvat_worker_webhooks:
    environment:
      SMOKESCREEN_OPTS: --unsafe-allow-private-ranges
```

### 2. Webhook Integration
**Webhook URL**: `http://localhost:5000/webhook`
**Events Subscribed**:
- `job:updated` - Job status changes
- `task:completed` - Task completion

**Payload Structure**:
```json
{
  "event": "job:updated",
  "job": {
    "id": 123,
    "status": "completed",
    "task": {"id": 456},
    "assignee": {"username": "annotator1"}
  }
}
```

### 3. Database Connections
**Connection String**: `postgresql://postgres:password@localhost:5432/cvat_annotations`
**Connection Pooling**: Implemented for concurrent access
**Transaction Management**: ACID compliance for data integrity

---

## Security Considerations

### 1. Authentication & Authorization
- **CVAT Integration**: Token-based API authentication
- **Database Access**: Username/password authentication with connection encryption
- **Webhook Endpoints**: IP-based filtering for localhost access

### 2. Data Protection
- **Annotation Data**: Stored with annotator attribution for audit trails
- **Video Content**: Processed locally to maintain data privacy
- **Database Backups**: Regular automated backups with encryption

### 3. Network Security
- **Internal Communication**: Services communicate over localhost
- **Docker Networks**: Isolated container networking
- **Port Exposure**: Minimal external port exposure

---

## Scalability Design

### 1. Horizontal Scaling
- **Multiple Annotators**: Support for unlimited concurrent annotators
- **Task Parallelization**: Independent task processing
- **Database Sharding**: Future support for data partitioning

### 2. Performance Optimization
- **Batch Processing**: Bulk operations for task creation and data retrieval
- **Caching**: In-memory caching for frequently accessed data
- **Async Processing**: Event-driven architecture prevents blocking

### 3. Resource Management
- **Docker Containerization**: Isolated resource allocation
- **Database Connection Pooling**: Efficient connection management
- **Memory Management**: Streaming processing for large datasets

### 4. Monitoring & Observability
- **Task Status Tracking**: Real-time status updates
- **Quality Metrics**: Automated calculation and alerting
- **System Health**: Container health checks and restart policies

---

## Deployment Architecture

### Development Environment
```
Local Machine
├── CVAT (Docker Compose)
├── PostgreSQL (Docker Container)
├── Application Services (Python Virtual Environment)
└── File Storage (Local File System)
```

### Production Considerations
- **Container Orchestration**: Kubernetes deployment
- **Load Balancing**: NGINX reverse proxy
- **Database**: Managed PostgreSQL service
- **Storage**: Distributed file system (e.g., NFS, S3)
- **Monitoring**: Prometheus + Grafana stack

---

This architecture provides a robust foundation for scaling video annotation workflows while maintaining data quality and system reliability. The modular design allows for future enhancements and integration with additional computer vision tools.