function [msg, num_read] = pblib_generic_parse_from_string(...
    buffer, descriptor, buffer_start, buffer_end)
%pblib_generic_parse_from_string
%   [msg, num_read] = pblib_generic_parse_from_string(buffer, descriptor, buffer_start, buffer_end)
%
%   INPUTS:
%       buffer       : buffer to parse proto message from
%       descriptor   : a proto message descriptor, as generated by one of the read functions
%       buffer_start : optional buffer start index, used so we can avoid reallocating the buffer
%       buffer_end   : optional buffer end index, used so we can avoid reallocating the buffer

%   protobuf-matlab - FarSounder's Protocol Buffer support for Matlab
%   Copyright (c) 2008, FarSounder Inc.  All rights reserved.
%   http://code.google.com/p/protobuf-matlab/
%  
%   Redistribution and use in source and binary forms, with or without
%   modification, are permitted provided that the following conditions are met:
%  
%       * Redistributions of source code must retain the above copyright
%   notice, this list of conditions and the following disclaimer.
%  
%       * Redistributions in binary form must reproduce the above copyright
%   notice, this list of conditions and the following disclaimer in the
%   documentation and/or other materials provided with the distribution.
%  
%       * Neither the name of the FarSounder Inc. nor the names of its
%   contributors may be used to endorse or promote products derived from this
%   software without specific prior written permission.
%  
%   THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
%   AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
%   IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
%   ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
%   LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
%   CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
%   SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
%   INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
%   CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
%   ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
%   POSSIBILITY OF SUCH DAMAGE.

%   Author: fedor.labounko@gmail.com (Fedor Labounko)
%   Support function used by Protobuf compiler generated .m files.

  if (nargin < 3)
    buffer_start = 1;
  end
  if (nargin < 4)
    buffer_end = length(buffer);
  end

  % Label enum
  LABEL_OPTIONAL = 1;
  LABEL_REQUIRED = 2;
  LABEL_REPEATED = 3;

  % Create the has_field map and set default values
  msg.has_field = java.util.HashMap;
  for field=descriptor.fields
    put(msg.has_field, field.name, 0);
    msg.(field.name) = field.default_value;
  end

  msg.unknown_fields = [];
  num_read = buffer_start - 1;
  while (num_read < buffer_end)
    [number, wire_type, tag_len] = pblib_read_tag(buffer, num_read + 1);
    index = get(descriptor.field_indeces_by_number, number);
    [wire_value, temp_num_read] = pblib_read_wire_type(buffer, num_read + tag_len + 1, wire_type);
    if (~isempty(index))
      field = descriptor.fields(index);
      if (field.wire_type ~= wire_type && ~field.options.packed)
        error('proto:read:wire_type_mismatch', ...
              ['Wire type mismatch while reading ' field.name ...
               '. Got ' num2str(wire_type) ' but expected ' ...
               num2str(field.wire_type)]);
      end
      if field.label == LABEL_REPEATED
        if field.options.packed
          msg.(field.name) = read_packed_field(field, wire_value);
        else
          % strings and byte arrays must be stored in cell arrays
          % and so need special treatment
          if (field.matlab_type == 7 || field.matlab_type == 8) % 'string' or 'bytes'
            if (get(msg.has_field, field.name))
              msg.(field.name) = [msg.(field.name) field.read_function(wire_value)];
            else
              msg.(field.name) = {field.read_function(wire_value)};
            end
          else
            msg.(field.name) = [msg.(field.name) field.read_function(wire_value)];
          end
        end
      else
        msg.(field.name) = field.read_function(wire_value);
      end
      put(msg.has_field, field.name, 1);
    else
      msg.unknown_fields = [...
          msg.unknown_fields struct(...
              'number', number, 'wire_type', wire_type, ...
              'raw_data', buffer(num_read + 1 : num_read + tag_len + temp_num_read))];
    end
    num_read = num_read + tag_len + temp_num_read;
  end

  % Check to make sure required fields have been read in We will only issue a warning if
  % they haven't so that debugging the final message would be easier
  for field=descriptor.fields
    if field.label == LABEL_REQUIRED && ~get(msg.has_field, field.name)
      warning('proto:read:required_enforcement', ...
              'Required field not set while parsing. This is an error.')
    end
  end

function [values] = read_packed_field(field, wire_value)
  [wire_value, buffer_start, buffer_end] = deal(wire_value{:});
  wire_values_length = buffer_end - buffer_start + 1;
  matlab_type_str = pblib_matlab_type_to_string(field.matlab_type);
  values = zeros(...
      [1 ceil(wire_values_length / ...
              pblib_type_to_estimated_encoded_length(field.type))], ...
      matlab_type_str);
  bytes_read_in = buffer_start - 1;
  num_values = 0;
  while bytes_read_in < buffer_end
    [num, num_read] = pblib_read_wire_type(wire_value, bytes_read_in + 1, field.wire_type);
    value = field.read_function(num);
    num_values = num_values + 1;
    values(num_values) = value;
    bytes_read_in = bytes_read_in + num_read;
  end
  values = values(1:num_values);
