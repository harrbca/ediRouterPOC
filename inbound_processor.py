#!/usr/bin/env python3
"""
EDI Inbound Processor
Downloads X12 EDI files from partner FTP/SFTP servers and saves them locally.
"""

import os
import json
import logging
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


class InboundProcessor:
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
        log_filename = os.path.join(log_folder, f"inbound_{datetime.now().strftime('%Y-%m-%d')}.log")

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
        self.logger.info("Inbound Processor Started")
        self.logger.info("="*80)

    def process_ftp_partner(self, partner):
        """Process inbound files from partner's FTP server."""
        files_downloaded = 0

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

            # Change to inbound directory
            ftp.cwd(partner['inbound_path'])

            # List files
            files = ftp.nlst()
            self.logger.info(f"Found {len(files)} file(s) on {partner['partner_name']} FTP")

            # Process each file
            for filename in files:
                # Skip files that start with X (already processed)
                if filename.startswith('X'):
                    self.logger.debug(f"Skipping already processed file: {filename}")
                    continue

                try:
                    # Download file
                    local_path = os.path.join(
                        self.master_config['local_folders']['inbound_dropoff'],
                        filename
                    )

                    with open(local_path, 'wb') as local_file:
                        ftp.retrbinary(f'RETR {filename}', local_file.write)

                    self.logger.info(f"Downloaded: {filename} from {partner['partner_name']}")

                    # Rename file on FTP server to mark as processed
                    new_filename = f"X{filename}"
                    ftp.rename(filename, new_filename)
                    self.logger.info(f"Renamed remote file: {filename} -> {new_filename}")

                    files_downloaded += 1

                except Exception as e:
                    self.logger.error(f"Error processing file {filename} from {partner['partner_name']}: {str(e)}")

            ftp.quit()
            return files_downloaded

        except Exception as e:
            self.logger.error(f"FTP connection failed for {partner['partner_name']}: {str(e)}")
            return files_downloaded
        finally:
            # Restore stdout
            if old_stdout is not None:
                sys.stdout = old_stdout

    def process_sftp_partner(self, partner):
        """Process inbound files from partner's SFTP server."""
        files_downloaded = 0

        try:
            self.logger.info(f"Connecting to SFTP server: {partner['host']}:{partner['port']}")

            # Create SSH client
            transport = paramiko.Transport((partner['host'], partner['port']))
            transport.connect(username=partner['username'], password=partner['password'])

            sftp = paramiko.SFTPClient.from_transport(transport)

            # Change to inbound directory
            sftp.chdir(partner['inbound_path'])

            # List files
            files = sftp.listdir()
            self.logger.info(f"Found {len(files)} file(s) on {partner['partner_name']} SFTP")

            # Process each file
            for filename in files:
                # Skip directories and files that start with X (already processed)
                try:
                    file_attr = sftp.stat(filename)
                    if not paramiko.sftp_attr.S_ISREG(file_attr.st_mode):
                        continue
                except:
                    continue

                if filename.startswith('X'):
                    self.logger.debug(f"Skipping already processed file: {filename}")
                    continue

                try:
                    # Download file
                    local_path = os.path.join(
                        self.master_config['local_folders']['inbound_dropoff'],
                        filename
                    )

                    sftp.get(filename, local_path)
                    self.logger.info(f"Downloaded: {filename} from {partner['partner_name']}")

                    # Rename file on SFTP server to mark as processed
                    new_filename = f"X{filename}"
                    sftp.rename(filename, new_filename)
                    self.logger.info(f"Renamed remote file: {filename} -> {new_filename}")

                    files_downloaded += 1

                except Exception as e:
                    self.logger.error(f"Error processing file {filename} from {partner['partner_name']}: {str(e)}")

            sftp.close()
            transport.close()
            return files_downloaded

        except Exception as e:
            self.logger.error(f"SFTP connection failed for {partner['partner_name']}: {str(e)}")
            return files_downloaded

    def process_partner(self, partner):
        """Process a single partner based on their protocol."""
        self.logger.info(f"Processing partner: {partner['partner_name']} (ID: {partner['partner_id']})")

        if partner['protocol'].lower() == 'ftp':
            return self.process_ftp_partner(partner)
        elif partner['protocol'].lower() == 'sftp':
            return self.process_sftp_partner(partner)
        else:
            self.logger.error(f"Unknown protocol '{partner['protocol']}' for partner {partner['partner_name']}")
            return 0

    def run(self):
        """Main processing loop."""
        # Ensure dropoff folder exists
        dropoff_folder = self.master_config['local_folders']['inbound_dropoff']
        Path(dropoff_folder).mkdir(parents=True, exist_ok=True)

        # Get enabled partners
        enabled_partners = [p for p in self.partners_config['partners'] if p.get('enabled', False)]

        if not enabled_partners:
            self.logger.info("No enabled partners found")
            return

        self.logger.info(f"Processing {len(enabled_partners)} enabled partner(s)")

        # Process each partner
        total_downloaded = 0
        for partner in enabled_partners:
            try:
                downloaded = self.process_partner(partner)
                total_downloaded += downloaded
            except Exception as e:
                self.logger.error(f"Unexpected error processing partner {partner['partner_name']}: {str(e)}")

        # Summary
        self.logger.info("="*80)
        self.logger.info(f"Processing complete: {total_downloaded} file(s) downloaded")
        self.logger.info("="*80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='EDI Inbound Processor - Download EDI files from partner FTP/SFTP servers')
    parser.add_argument('--master-config', '-m',
                        default='master_config.json',
                        help='Path to master configuration file (default: master_config.json)')
    parser.add_argument('--partners-config', '-p',
                        default='partners.json',
                        help='Path to partners configuration file (default: partners.json)')

    args = parser.parse_args()

    processor = InboundProcessor(
        master_config_path=args.master_config,
        partners_config_path=args.partners_config
    )
    processor.run()