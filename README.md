# EDI Router - Proof of Concept

Automated X12 EDI file routing system for processing inbound and outbound EDI documents with trading partners via FTP/SFTP.

## Overview

This system consists of two main scripts:
- **outbound_processor.py** - Sends EDI files from your ERP to partner FTP servers
- **inbound_processor.py** - Downloads EDI files from partner FTP servers to your ERP pickup folder

## Setup

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Folders

Edit `master_config.json` to set your local folder paths:

```json
{
  "local_folders": {
    "outbound_pickup": "C:/edi/outbound",      # Where ERP drops outbound files
    "outbound_archive": "C:/edi/outbound/archive",  # Where processed files are archived
    "inbound_dropoff": "C:/edi/inbound"        # Where ERP picks up inbound files
  },
  "archive_templates": {
    "archive_path_template": "",                # Optional: subdirectory structure (e.g., "{partner_id}/{year}/{month}")
    "archive_filename_template": "{filename}_{timestamp}.{extension}"  # Archive filename pattern
  },
  "logging": {
    "log_folder": "C:/edi/logs",
    "log_level": "INFO",
    "ftp_debug_level": 0
  }
}
```

**Archive Template Placeholders:**
- `{filename}` - Original filename without extension
- `{extension}` - Original file extension (without dot)
- `{partner_id}` - Partner/receiver ID from ISA08
- `{partner_name}` - Partner name from config (spaces replaced with underscores)
- `{timestamp}` - Full timestamp (YYYYMMDD_HHMMSS)
- `{date}` - Date only (YYYYMMDD)
- `{time}` - Time only (HHMMSS)
- `{year}`, `{month}`, `{day}` - Individual date components
- `{hour}`, `{minute}`, `{second}` - Individual time components

**Template Examples:**
```
# Simple filename with timestamp
"{filename}_{timestamp}.{extension}"
→ 000000323_20260109_123045.832

# With partner ID
"{filename}-{partner_id}-{timestamp}.{extension}"
→ 000000323-6048558786-20260109_123045.832

# Partner name in filename
"{partner_name}_{date}_{filename}.{extension}"
→ INNOVATIVE_FLOORING_LTD_20260109_000000323.832

# Organize by partner and date
archive_path_template: "{partner_id}/{year}/{month}"
→ archive/6048558786/2026/01/filename.832
```

### 3. Configure Partners

Edit `partners.json` with your trading partner details:

```json
{
  "partners": [
    {
      "partner_id": "6048558786",              # Partner ID from ISA segment
      "partner_name": "Partner A - Example",
      "protocol": "sftp",                       # "ftp" or "sftp"
      "host": "ftp.partnera.com",
      "port": 22,                               # 21 for FTP, 22 for SFTP
      "username": "user123",
      "password": "pass123",
      "outbound_path": "/inbound",              # Partner's inbound folder (our outbound)
      "inbound_path": "/outbound",              # Partner's outbound folder (our inbound)
      "enabled": true,
      "archive_path_template": "{partner_id}/{year}",           # Optional: override global archive path
      "archive_filename_template": "{filename}_{date}.{extension}"  # Optional: override global archive filename
    }
  ]
}
```

**Important:**
- The `partner_id` must match the ISA08 field (receiver ID) in your outbound X12 files.
- Per-partner archive templates are optional and will override the global templates from `master_config.json` if specified.

## Usage

### Outbound Processing (Your ERP → Partners)

Run manually:
```bash
python outbound_processor.py
```

With custom config files:
```bash
python outbound_processor.py --master-config /path/to/master_config.json --partners-config /path/to/partners.json
```

Or using short options:
```bash
python outbound_processor.py -m /path/to/master_config.json -p /path/to/partners.json
```

The script will:
1. Scan the `outbound_pickup` folder for EDI files
2. Parse each file's ISA segment to extract the partner ID (ISA08)
3. Look up the partner configuration
4. Upload the file to the partner's FTP/SFTP server
5. Archive the processed file with a timestamp

### Inbound Processing (Partners → Your ERP)

Run manually:
```bash
python inbound_processor.py
```

With custom config files:
```bash
python inbound_processor.py --master-config /path/to/master_config.json --partners-config /path/to/partners.json
```

Or using short options:
```bash
python inbound_processor.py -m /path/to/master_config.json -p /path/to/partners.json
```

The script will:
1. Connect to each enabled partner's FTP/SFTP server
2. List files in their outbound folder
3. Download files that don't start with "X"
4. Rename downloaded files on the partner server with "X" prefix (marks as processed)
5. Save files to your `inbound_dropoff` folder for ERP pickup

## Scheduling

### Windows (Task Scheduler)

Create two scheduled tasks:

**Outbound Task:**
```
Program: C:\Python\python.exe
Arguments: C:\path\to\outbound_processor.py
Start in: C:\path\to\ediRouter
Schedule: Every 15 minutes (or as needed)
```

**Inbound Task:**
```
Program: C:\Python\python.exe
Arguments: C:\path\to\inbound_processor.py
Start in: C:\path\to\ediRouter
Schedule: Every 15 minutes (or as needed)
```

### Linux (Cron)

Add to crontab:

```bash
# Run outbound processor every 15 minutes
*/15 * * * * cd /path/to/ediRouter && /usr/bin/python3 outbound_processor.py

# Run inbound processor every 15 minutes
*/15 * * * * cd /path/to/ediRouter && /usr/bin/python3 inbound_processor.py
```

## Logging

Logs are written to the folder specified in `master_config.json` with daily log files:
- `outbound_YYYY-MM-DD.log` - Outbound processing logs
- `inbound_YYYY-MM-DD.log` - Inbound processing logs

Each log includes:
- Timestamp of operations
- Files processed
- Partner information
- Success/failure status
- Detailed error messages

### FTP Debugging

To troubleshoot FTP connection issues, set `ftp_debug_level` in `master_config.json`:

```json
"logging": {
  "log_folder": "C:/edi/logs",
  "log_level": "INFO",
  "ftp_debug_level": 2
}
```

**FTP Debug Levels:**
- `0` - No FTP debugging (default)
- `1` - Show FTP commands and responses
- `2` - Show FTP commands, responses, and more verbose output

When enabled, FTP protocol commands and server responses will be written to the console and log files, helping diagnose connection, authentication, or path issues.

## File Processing Flow

### Outbound Flow
```
ERP System → outbound_pickup/ → outbound_processor.py → Partner FTP → outbound_archive/
```

### Inbound Flow
```
Partner FTP → inbound_processor.py → inbound_dropoff/ → ERP System
```

## Troubleshooting

1. **"No partner configuration found"** - Check that the partner_id in `partners.json` matches ISA08 in the EDI file
2. **FTP connection errors** - Verify host, port, username, and password in `partners.json`. Enable FTP debugging by setting `ftp_debug_level: 2` in `master_config.json` to see detailed FTP protocol commands and responses.
3. **Files not processing** - Check folder permissions and paths in `master_config.json`
4. **"Already processed" files accumulating** - Files starting with "X" on partner FTP are skipped; manually remove if needed

## Security Note

This is a proof of concept with plaintext passwords in `partners.json`. For production use, consider:
- Encrypting the partners configuration file
- Using SSH keys for SFTP instead of passwords
- Implementing secure credential storage
- Adding file encryption for sensitive data

## File Structure

```
ediRouter/
├── outbound_processor.py      # Outbound processing script
├── inbound_processor.py        # Inbound processing script
├── master_config.json          # Local folder configuration
├── partners.json               # Trading partner configurations
├── requirements.txt            # Python dependencies
├── README.md                   # This file
└── samples/                    # Sample X12 files
    ├── outbound_to_customer/
    └── inbound_from_customer/
```