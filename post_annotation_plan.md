# Efficient Post-Annotation Workflow System

A streamlined, webhook-driven system for processing CVAT annotations with automated quality control and dataset generation.

## Overview

This system eliminates the inefficiency of polling CVAT for completed tasks by implementing a webhook-based notification system. It provides real-time processing of annotations, structured data storage, automated quality control, and seamless dataset generation.

## Architecture

The workflow consists of four main stages:

1. **Automated Retrieval** - Webhook notifications from CVAT
2. **Structured Storage** - Database-backed annotation storage
3. **Quality Control** - Automated IAA and Kappa calculations
4. **Dataset Generation** - Final AVA CSV output

## System Flow

```
┌─────────────────────────────────┐
│ 1. Annotator completes job      │
│    in CVAT UI (Status changes)  │
└─────────────────────────────────┘
              │
              ▼ (Instant Trigger)
┌─────────────────────────────────┐
│ EFFICIENT: CVAT Webhook         │
│ sends notification to your      │
│ server's API endpoint           │
└─────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│ 2. Backend Server               │
│  - Exports annotations (XML)    │
└─────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│ 3. Persistent Database          │
│  - Stores Parsed Data           │
│    (for fast queries)           │
└─────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────┐      ┌────────────────────────────────┐
│ 4. Admin Dashboard              │─────▶│ IAACalculator & Kappa Check    │
│  - Admin reviews QC scores      │      │ (Queries the fast DB)          │
└─────────────────────────────────┘      └────────────────────────────────┘
              │
              ▼ (If QC Passes)
┌─────────────────────────────────┐
│ 5. AVADatasetGenerator          │
│  - Reads approved data          │
│  - Appends to final CSV         │
└─────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│ 6. Final AVA_Dataset.csv        │
└─────────────────────────────────┘
```

## Components

### 1. CVAT Webhook Handler
**Purpose**: Receives instant notifications when annotation jobs are completed.

**Key Features**:
- Eliminates polling overhead
- Real-time processing triggers
- Automatic XML export initiation

**Configuration**: Set up webhook in CVAT project settings pointing to your API endpoint.

### 2. Database Storage System
**Purpose**: Stores parsed annotation data in a structured, queryable format.

**Recommended Database**: PostgreSQL

**Benefits**:
- Fast queries and filtering
- Structured data relationships
- Efficient comparison operations
- Backup of raw XML files

### 3. Quality Control Module
**Purpose**: Automated quality assessment using Inter-Annotator Agreement (IAA) and Kappa calculations.

**Features**:
- `IAACalculator` service integration
- Automated quality scoring
- Admin dashboard for review
- Batch approval/rejection workflow

### 4. Dataset Generation Service
**Purpose**: Creates final AVA format datasets from approved annotations.

**Features**:
- `AVADatasetGenerator` service
- Consensus logic for overlapping clips
- AVA CSV format compliance
- Master dataset file management

## Prerequisites

- CVAT instance with webhook support
- PostgreSQL database
- Backend server with API capabilities
- Admin dashboard interface

## Installation

1. **Database Setup**
   ```sql
   -- Create tables for annotations, clips, tracks, and attributes
   -- (Specific schema depends on your annotation structure)
   ```

2. **Webhook Configuration**
   - Navigate to CVAT project settings
   - Add webhook URL pointing to your server endpoint
   - Configure trigger events (job status changes)

3. **Backend Services**
   - Deploy webhook handler endpoint
   - Configure database connections
   - Set up IAACalculator service
   - Initialize AVADatasetGenerator service

4. **Admin Dashboard**
   - Deploy quality control interface
   - Configure database queries
   - Set up approval workflow

## Usage

### For Annotators
1. Complete annotation tasks in CVAT
2. Change job status to "completed"
3. System automatically processes the annotations

### For Administrators
1. Access admin dashboard
2. Review quality control scores
3. Approve or reject annotation batches
4. Monitor dataset generation progress

## API Endpoints

### Webhook Receiver
```
POST /webhook/cvat-completion
```
Receives CVAT job completion notifications.

### Quality Control
```
GET /api/quality-control/batch/{batch_id}
```
Retrieves quality scores for a specific batch.

### Dataset Status
```
GET /api/dataset/status
```
Returns current dataset generation status.

## Configuration

### Environment Variables
```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/annotations

# CVAT
CVAT_SERVER_URL=https://your-cvat-instance.com
CVAT_API_TOKEN=your-api-token

# Quality Control Thresholds
MIN_IAA_SCORE=0.7
MIN_KAPPA_SCORE=0.6
```

### Webhook Configuration
```json
{
  "webhook_url": "https://your-server.com/webhook/cvat-completion",
  "events": ["job:updated"],
  "secret": "your-webhook-secret"
}
```

## Benefits Over Polling

| Aspect | Polling | Webhook (This System) |
|--------|---------|----------------------|
| **Efficiency** | Constant server requests | Instant notifications only |
| **Latency** | Depends on polling interval | Real-time processing |
| **Resource Usage** | High (continuous requests) | Low (event-driven) |
| **Scalability** | Poor | Excellent |
| **Reliability** | Can miss updates | Guaranteed delivery |

## Troubleshooting

### Common Issues

**Webhook not triggering**
- Verify webhook URL is accessible
- Check CVAT webhook configuration
- Validate webhook secret

**Database performance issues**
- Add indexes on frequently queried columns
- Consider connection pooling
- Monitor query performance

**Quality control failures**
- Check IAA calculation logic
- Verify overlapping clip detection
- Review consensus algorithm

## Contributing

1. Fork the repository
2. Create a feature branch
3. Implement changes with tests
4. Submit a pull request

## License

[Insert your license information here]

## Support

For questions or issues:
- Create an issue in the repository
- Contact the development team
- Check the troubleshooting guide above

---

**Note**: This README assumes familiarity with CVAT, PostgreSQL, and basic web development concepts. Adjust the technical level based on your team's expertise.