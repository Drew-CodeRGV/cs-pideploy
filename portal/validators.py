"""
Form validation logic for captive portal.

This module provides validation functions for registration form fields
including email, phone, zip code, and date of birth.
"""

import re
from datetime import datetime, date
from typing import Tuple, Dict, Any


class FormValidator:
    """Form validation logic for captive portal registration."""
    
    # Email regex pattern (basic validation)
    EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    
    # Phone pattern (exactly 10 digits)
    PHONE_PATTERN = re.compile(r'^\d{10}$')
    
    # Zip code pattern (exactly 5 digits)
    ZIP_PATTERN = re.compile(r'^\d{5}$')
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """
        Validate email format.
        
        Args:
            email: Email address to validate
        
        Returns:
            True if valid email format, False otherwise
        
        Examples:
            >>> FormValidator.validate_email("test@example.com")
            True
            >>> FormValidator.validate_email("not-an-email")
            False
        """
        if not email or not isinstance(email, str):
            return False
        return bool(FormValidator.EMAIL_PATTERN.match(email.strip()))
    
    @staticmethod
    def validate_phone(phone: str) -> bool:
        """
        Validate phone number is exactly 10 digits.
        
        Args:
            phone: Phone number to validate
        
        Returns:
            True if exactly 10 digits, False otherwise
        
        Examples:
            >>> FormValidator.validate_phone("5125551234")
            True
            >>> FormValidator.validate_phone("512-555-1234")
            False
            >>> FormValidator.validate_phone("123")
            False
        """
        if not phone or not isinstance(phone, str):
            return False
        return bool(FormValidator.PHONE_PATTERN.match(phone.strip()))
    
    @staticmethod
    def validate_zip(zip_code: str) -> bool:
        """
        Validate zip code is exactly 5 digits.
        
        Args:
            zip_code: Zip code to validate
        
        Returns:
            True if exactly 5 digits, False otherwise
        
        Examples:
            >>> FormValidator.validate_zip("78701")
            True
            >>> FormValidator.validate_zip("78701-1234")
            False
            >>> FormValidator.validate_zip("123")
            False
        """
        if not zip_code or not isinstance(zip_code, str):
            return False
        return bool(FormValidator.ZIP_PATTERN.match(zip_code.strip()))
    
    @staticmethod
    def validate_dob(dob: str) -> bool:
        """
        Validate date of birth is a valid date in the past.
        
        Args:
            dob: Date of birth in ISO format (YYYY-MM-DD)
        
        Returns:
            True if valid past date, False otherwise
        
        Examples:
            >>> FormValidator.validate_dob("1990-01-15")
            True
            >>> FormValidator.validate_dob("2050-01-15")
            False
            >>> FormValidator.validate_dob("not-a-date")
            False
        """
        if not dob or not isinstance(dob, str):
            return False
        
        try:
            # Parse date
            dob_date = datetime.fromisoformat(dob.strip()).date()
            
            # Check if in the past
            today = date.today()
            return dob_date < today
        except (ValueError, AttributeError):
            return False
    
    @staticmethod
    def validate_required_field(value: Any, field_name: str) -> Tuple[bool, str]:
        """
        Validate that a required field is not empty.
        
        Args:
            value: Field value to validate
            field_name: Name of the field (for error message)
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            return False, f"{field_name} is required"
        return True, ""
    
    @staticmethod
    def validate_registration(data: Dict[str, Any]) -> Tuple[bool, Dict[str, str]]:
        """
        Validate complete registration form data.
        
        Args:
            data: Dictionary containing form data with keys:
                - first_name: First name (required)
                - last_name: Last name (required)
                - email: Email address (required, must be valid format)
                - phone: Phone number (required, must be 10 digits)
                - zip: Zip code (required, must be 5 digits)
                - dob: Date of birth (required, must be valid past date)
                - raffle_opt_in: Boolean (optional)
        
        Returns:
            Tuple of (is_valid, errors_dict)
            - is_valid: True if all validations pass, False otherwise
            - errors_dict: Dictionary mapping field names to error messages
        
        Examples:
            >>> data = {
            ...     "first_name": "John",
            ...     "last_name": "Doe",
            ...     "email": "john@example.com",
            ...     "phone": "5125551234",
            ...     "zip": "78701",
            ...     "dob": "1990-01-15"
            ... }
            >>> is_valid, errors = FormValidator.validate_registration(data)
            >>> is_valid
            True
            >>> errors
            {}
        """
        errors = {}
        
        # Required fields
        required_fields = ['first_name', 'last_name', 'email', 'phone', 'zip', 'dob']
        
        for field in required_fields:
            is_valid, error_msg = FormValidator.validate_required_field(
                data.get(field), 
                field.replace('_', ' ').title()
            )
            if not is_valid:
                errors[field] = error_msg
        
        # If required fields are missing, return early
        if errors:
            return False, errors
        
        # Email format validation
        if not FormValidator.validate_email(data['email']):
            errors['email'] = "Please enter a valid email address"
        
        # Phone validation
        if not FormValidator.validate_phone(data['phone']):
            errors['phone'] = "Phone number must be exactly 10 digits"
        
        # Zip code validation
        if not FormValidator.validate_zip(data['zip']):
            errors['zip'] = "Zip code must be exactly 5 digits"
        
        # Date of birth validation
        if not FormValidator.validate_dob(data['dob']):
            errors['dob'] = "Please enter a valid date of birth in the past"
        
        # Check if all validations passed
        is_valid = len(errors) == 0
        
        return is_valid, errors
    
    @staticmethod
    def validate_survey_response(response: Dict[str, str], question_type: str) -> Tuple[bool, str]:
        """
        Validate a single survey response based on question type.
        
        Args:
            response: Dictionary with 'question_id' and 'answer' keys
            question_type: Type of question (yes_no, yes_no_maybe, scale_1_5, short_text, long_text)
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        answer = response.get('answer', '')
        
        # Check for empty answer (allowed - survey is optional)
        if not answer or not answer.strip():
            return True, ""
        
        # Validate based on question type
        if question_type == 'yes_no':
            if answer not in ['Yes', 'No']:
                return False, "Answer must be 'Yes' or 'No'"
        
        elif question_type == 'yes_no_maybe':
            if answer not in ['Yes', 'No', 'Maybe']:
                return False, "Answer must be 'Yes', 'No', or 'Maybe'"
        
        elif question_type == 'scale_1_5':
            if answer not in ['1', '2', '3', '4', '5']:
                return False, "Answer must be a number from 1 to 5"
        
        elif question_type == 'short_text':
            if len(answer) > 255:
                return False, "Answer must be 255 characters or less"
        
        elif question_type == 'long_text':
            if len(answer) > 400:
                return False, "Answer must be 400 characters or less"
        
        return True, ""
