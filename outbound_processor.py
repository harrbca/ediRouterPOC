#!/usr/bin/env python3
"""
EDI Outbound Processor
Processes X12 EDI files from local folder and sends them to partner FTP/SFTP servers.
"""

import os
import json
import logging
import shutil
import argparse
import sys
from datetime import datetime
from pathlib import Path
from ftplib import FTP
import paramiko


class LoggerWriter:
    """File-like object that redirects writes to a logger."""
    def __init__(self, logger, level=logging.INFO):
        self.logger = logger
        self.level = level
        self.buffer = ''

    def write(self, message):
        if message and message != '\n':
            # Strip trailing newline if present
            message = message.rstrip('\n')
            if message:
                self.logger.log(self.level, message)

    def flush(self):
        pass


class OutboundProcessor:
    def __init__(self, master_config_path='master_config.json', partners_config_path='partners.json'):
        """Initialize the processor with configuration files."""
        self.master_config = self._load_json(master_config_path)
        self.partners_config = self._load_json(partners_config_path)
        self.setup_logging()

    def _load_json(self, file_path):
        """Load and parse JSON configuration file."""
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            raise Exception(f"Configuration file not found: {file_path}")
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON in {file_path}: {str(e)}")

    def setup_logging(self):
        """Configure logging to file and console."""
        log_folder = self.master_config['logging']['log_folder']
        log_level = self.master_config['logging']['log_level']

        # Create log folder if it doesn't exist
        Path(log_folder).mkdir(parents=True, exist_ok=True)

        # Create log filename with today's date
        log_filename = os.path.join(log_folder, f"outbound_{datetime.now().strftime('%Y-%m-%d')}.log")

        # Configure logging
        logging.basicConfig(
            level=getattr(logging, log_level),
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_filename),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        self.logger.info("="*80)
        self.logger.info("Outbound Processor Started")
        self.logger.info("="*80)

    def parse_isa_segment(self, file_path):
        """
        Parse ISA segment from X12 file and extract partner ID from ISA08.
        Returns the partner ID or None if parsing fails.
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                first_line = f.readline().strip()

            # ISA segment should start with 'ISA*'
            if not first_line.startswith('ISA*'):
                self.logger.error(f"File does not start with ISA segment: {file_path}")
                return None

            # Split by delimiter (typically *)
            segments = first_line.split('*')

            # ISA08 is at index 8 (0-based, ISA itself is at index 0)
            if len(segments) > 8:
                partner_id = segments[8].strip()
                self.logger.info(f"Extracted partner ID: {partner_id} from file: {os.path.basename(file_path)}")
                return partner_id
            else:
                self.logger.error(f"ISA segment incomplete in file: {file_path}")
                return None

        except Exception as e:
            self.logger.error(f"Error parsing ISA segment from {file_path}: {str(e)}")
            return None

    def find_partner(self, partner_id):
        """Find partner configuration by partner ID."""
        for partner in self.partners_config['partners']:
            if partner['partner_id'] == partner_id and partner['enabled']:
                return partner
        return None

    def upload_via_ftp(self, file_path, partner):
        """Upload file to partner's FTP server."""
        # Redirect stdout to logger if FTP debugging is enabled
        ftp_debug_level = self.master_config.get('logging', {}).get('ftp_debug_level', 0)
        old_stdout = None
        if ftp_debug_level > 0:
            old_stdout = sys.stdout
            sys.stdout = LoggerWriter(self.logger, logging.INFO)

        try:
            self.logger.info(f"Connecting to FTP server: {partner['host']}:{partner['port']}")

            ftp = FTP()
            # Enable FTP debugging if configured
            if ftp_debug_level > 0:
                ftp.set_debuglevel(ftp_debug_level)

            ftp.connect(partner['host'], partner['port'])
            ftp.login(partner['username'], partner['password'])

            # Change to target directory
            ftp.cwd(partner['outbound_path'])

            # Upload file
            filename = os.path.basename(file_path)
            with open(file_path, 'rb') as f:
                ftp.storbinary(f'STOR {filename}', f)

            ftp.quit()
            self.logger.info(f"Successfully uploaded {filename} to {partner['partner_name']} via FTP")
            return True

        except Exception as e:
            self.logger.error(f"FTP upload failed for {partner['partner_name']}: {str(e)}")
            return False
        finally:
            # Restore stdout
            if old_stdout is not None:
                sys.stdout = old_stdout

    def upload_via_sftp(self, file_path, partner):
        """Upload file to partner's SFTP server."""
        try:
            self.logger.info(f"Connecting to SFTP server: {partner['host']}:{partner['port']}")

            # Create SSH client
            transport = paramiko.Transport((partner['host'], partner['port']))
            transport.connect(username=partner['username'], password=partner['password'])

            sftp = paramiko.SFTPClient.from_transport(transport)

            # Change to target directory
            sftp.chdir(partner['outbound_path'])

            # Upload file
            filename = os.path.basename(file_path)
            remote_path = f"{partner['outbound_path']}/{filename}"
            sftp.put(file_path, filename)

            sftp.close()
            transport.close()
            self.logger.info(f"Successfully uploaded {filename} to {partner['partner_name']} via SFTP")
            return True

        except Exception as e:
            self.logger.error(f"SFTP upload failed for {partner['partner_name']}: {str(e)}")
            return False

    def build_template_values(self, file_path, partner):
        """Build dictionary of template placeholder values."""
        filename = os.path.basename(file_path)
        name, ext = os.path.splitext(filename)
        ext = ext.lstrip('.')  # Remove leading dot

        now = datetime.now()

        return {
            'filename': name,
            'extension': ext,
            'partner_id': partner.get('partner_id', ''),
            'partner_name': partner.get('partner_name', '').replace(' ', '_'),
            'timestamp': now.strftime('%Y%m%d_%H%M%S'),
            'date': now.strftime('%Y%m%d'),
            'time': now.strftime('%H%M%S'),
            'year': now.strftime('%Y'),
            'month': now.strftime('%m'),
            'day': now.strftime('%d'),
            'hour': now.strftime('%H'),
            'minute': now.strftime('%M'),
            'second': now.strftime('%S')
        }

    def apply_template(self, template, values):
        """Replace template placeholders with actual values."""
        result = template
        for key, value in values.items():
            result = result.replace(f'{{{key}}}', str(value))
        return result

    def archive_file(self, file_path, partner):
        """Move processed file to archive folder with timestamp."""
        try:
            base_archive_folder = self.master_config['local_folders']['outbound_archive']

            # Get templates from partner config (if exists) or master config
            archive_templates = self.master_config.get('archive_templates', {})
            path_template = partner.get('archive_path_template',
                                       archive_templates.get('archive_path_template', ''))
            filename_template = partner.get('archive_filename_template',
                                           archive_templates.get('archive_filename_template',
                                                                '{filename}_{timestamp}.{extension}'))

            # Build template values
            template_values = self.build_template_values(file_path, partner)

            # Apply path template
            if path_template:
                subpath = self.apply_template(path_template, template_values)
                archive_folder = os.path.join(base_archive_folder, subpath)
            else:
                archive_folder = base_archive_folder

            # Create archive folder if needed
            Path(archive_folder).mkdir(parents=True, exist_ok=True)

            # Apply filename template
            archived_filename = self.apply_template(filename_template, template_values)

            # Build full path and move file
            archived_path = os.path.join(archive_folder, archived_filename)
            shutil.move(file_path, archived_path)

            original_filename = os.path.basename(file_path)
            relative_path = os.path.relpath(archived_path, base_archive_folder)
            self.logger.info(f"Archived file: {original_filename} -> {relative_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to archive file {file_path}: {str(e)}")
            return False

    def process_file(self, file_path):
        """Process a single EDI file."""
        filename = os.path.basename(file_path)
        self.logger.info(f"Processing file: {filename}")

        # Parse ISA segment to get partner ID
        partner_id = self.parse_isa_segment(file_path)
        if not partner_id:
            self.logger.error(f"Skipping file {filename}: Could not extract partner ID")
            return False

        # Find partner configuration
        partner = self.find_partner(partner_id)
        if not partner:
            self.logger.error(f"Skipping file {filename}: No partner configuration found for ID {partner_id}")
            return False

        self.logger.info(f"Partner found: {partner['partner_name']} (ID: {partner_id})")

        # Upload based on protocol
        upload_success = False
        if partner['protocol'].lower() == 'ftp':
            upload_success = self.upload_via_ftp(file_path, partner)
        elif partner['protocol'].lower() == 'sftp':
            upload_success = self.upload_via_sftp(file_path, partner)
        else:
            self.logger.error(f"Unknown protocol: {partner['protocol']}")
            return False

        # Archive file if upload was successful
        if upload_success:
            self.archive_file(file_path, partner)
            return True
        else:
            self.logger.error(f"File {filename} not archived due to upload failure")
            return False

    def run(self):
        """Main processing loop."""
        pickup_folder = self.master_config['local_folders']['outbound_pickup']

        # Check if pickup folder exists
        if not os.path.exists(pickup_folder):
            self.logger.error(f"Pickup folder does not exist: {pickup_folder}")
            return

        # Get all files in pickup folder
        files = [f for f in os.listdir(pickup_folder) if os.path.isfile(os.path.join(pickup_folder, f))]

        if not files:
            self.logger.info("No files found in pickup folder")
            return

        self.logger.info(f"Found {len(files)} file(s) to process")

        # Process each file
        success_count = 0
        error_count = 0

        for filename in files:
            file_path = os.path.join(pickup_folder, filename)
            try:
                if self.process_file(file_path):
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                self.logger.error(f"Unexpected error processing {filename}: {str(e)}")
                error_count += 1

        # Summary
        self.logger.info("="*80)
        self.logger.info(f"Processing complete: {success_count} succeeded, {error_count} failed")
        self.logger.info("="*80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='EDI Outbound Processor - Send EDI files to partner FTP/SFTP servers')
    parser.add_argument('--master-config', '-m',
                        default='master_config.json',
                        help='Path to master configuration file (default: master_config.json)')
    parser.add_argument('--partners-config', '-p',
                        default='partners.json',
                        help='Path to partners configuration file (default: partners.json)')

    args = parser.parse_args()

    processor = OutboundProcessor(
        master_config_path=args.master_config,
        partners_config_path=args.partners_config
    )
    processor.run()